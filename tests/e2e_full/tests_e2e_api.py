"""Full-system E2E — API 단계(실제 HTTP, 실제 uvicorn, 실제 PostgreSQL). 합성 데이터만.

브라우저가 다루기 어려운 권한·노출·불변식(401/403/404, 비공개 공고, IDOR, 직접 결정 경로)을 여기서 본다.
브라우저 시나리오(frontend/e2e/full-system.mjs)는 구직자 A·기업 담당자·관리자 계정을 쓰고,
이 모듈은 구직자 B·비멤버·관리자 2 와 별도 조직("E2E API 조직")을 써서 서로 상태가 섞이지 않게 한다.
"""
from __future__ import annotations

import io
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import psycopg

CSRF = {"X-CSRF-TOKEN": "1"}
V1 = "/api/v1"
JOBKOREA_DRAFT_ID = "e2e00000-0000-4000-8000-00000000d001"
JOBKOREA_DRAFT_MARK = "E2EJOBKOREADRAFT"
BACKEND = Path(__file__).resolve().parents[2] / "backend"


def signup(client: httpx.Client, email: str, password: str, name: str) -> dict:
    resp = client.get(f"{V1}/consent-policies")
    policies = resp.json()
    assert isinstance(policies, list), f"consent-policies {resp.status_code}: {resp.text[:300]}"
    consents = [{"policy_code": p["policy_code"], "policy_version": p["version"], "granted": True}
                for p in policies if p.get("is_required")]
    r = client.post(f"{V1}/auth/signup", headers=CSRF, json={"email": email, "password": password,
                                                             "display_name": name, "consents": consents})
    assert r.status_code == 201, f"signup {email}: {r.status_code} {r.text[:300]}"
    token = r.json()["access_token"]
    me = client.get(f"{V1}/me", headers={"Authorization": f"Bearer {token}"}).json()
    return {"email": email, "user_id": me["user_id"], "name": name}


def login(client: httpx.Client, email: str, password: str) -> dict:
    r = client.post(f"{V1}/auth/login", headers=CSRF, json={"email": email, "password": password})
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text[:200]}"
    return {"Authorization": f"Bearer {r.json()['access_token']}", **CSRF}


def pdf_bytes() -> bytes:
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>"]
    out, offsets = b"%PDF-1.7\n", [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    start = len(out)
    out += b"xref\n0 4\n0000000000 65535 f \n" + b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets[1:])
    return out + b"trailer\n<< /Size 4 /Root 1 0 R >>\n" + f"startxref\n{start}\n%%EOF".encode()


def worker(module: str, env: dict) -> str:
    res = subprocess.run([sys.executable, "-m", module], cwd=BACKEND, env=env, capture_output=True, text=True,
                         timeout=300)
    assert res.returncode == 0, f"{module} exit {res.returncode}: {res.stderr[-400:]}"
    return (res.stdout or "").strip()[-200:]


def expect(r: httpx.Response, *codes: int) -> httpx.Response:
    assert r.status_code in codes, f"{r.request.method} {r.request.url.path} -> {r.status_code} (want {codes}) {r.text[:300]}"
    return r


def run(rec, api: str, accounts: dict, password: str, admin_db: str, env: dict) -> dict:
    state: dict = {}
    c = httpx.Client(base_url=api, timeout=60)
    db = psycopg.connect(admin_db, autocommit=True)
    q = lambda s, *a: db.execute(s, a).fetchone()  # noqa: E731
    b = login(c, accounts["seeker_b"]["email"], password)
    a = login(c, accounts["seeker"]["email"], password)
    outsider = login(c, accounts["outsider"]["email"], password)
    admin2 = login(c, accounts["admin2"]["email"], password)
    company = login(c, accounts["company"]["email"], password)

    # ------------------------------------------------------------------ USER (API: 화면에 없는 기능 포함)
    def profile_patch():
        r = expect(c.patch(f"{V1}/me", headers=b, json={"headline": "E2E 헤드라인", "location_text": "서울"}), 200)
        me = expect(c.get(f"{V1}/me", headers=b), 200).json()
        assert me["profile"]["headline"] == "E2E 헤드라인", me
        return {"PATCH /me": r.status_code, "profile.headline": me["profile"]["headline"]}
    rec.check("USER", "A-profile", "API PATCH /me updates profile (no edit UI exists, see defect backlog)", profile_patch)

    def experience_crud():
        r = expect(c.post(f"{V1}/me/experiences", headers=b, json={"organization": "E2E 합성 회사", "title": "백엔드"}), 201)
        exp = r.json()
        key = "experience_id"
        r2 = expect(c.patch(f"{V1}/me/experiences/{exp[key]}", headers=b, json={"title": "백엔드 개발자"}), 200)
        assert r2.json()["title"] == "백엔드 개발자"
        state["seeker_b_experience"] = exp[key]
        r3 = expect(c.post(f"{V1}/me/experiences", headers=b, json={"organization": "E2E 삭제용", "title": "임시"}), 201)
        expect(c.delete(f"{V1}/me/experiences/{r3.json()[key]}", headers=b), 204)
        # 남의 경력 수정·삭제는 404
        expect(c.patch(f"{V1}/me/experiences/{exp[key]}", headers=outsider, json={"title": "x"}), 404)
        expect(c.delete(f"{V1}/me/experiences/{exp[key]}", headers=outsider), 404)
        return {"create": 201, "patch": 200, "delete": 204, "other_user_patch_delete": 404}
    rec.check("USER", "A-experience", "API experience create/patch/delete + other user 404", experience_crud)

    # ------------------------------------------------------------------ PUBLIC_POSTINGS (익명)
    seed_draft = q("SELECT job_posting_id::text FROM career.job_postings WHERE status='draft' AND source_id = "
                   "(SELECT source_id FROM career.data_sources WHERE code='synthetic_seed') LIMIT 1")[0]
    published = q("SELECT job_posting_id::text, title FROM career.job_postings WHERE status='published' "
                  "ORDER BY published_at DESC NULLS LAST LIMIT 1")
    state["published_posting"] = {"id": published[0], "title": published[1]}
    state["skill_names"] = [r[0] for r in db.execute("SELECT name FROM career.skills ORDER BY name LIMIT 2").fetchall()]
    # 브라우저(구직자 A)용: 다른 공개 공고(B 가 API 로 지원한 공고와 다른 것)
    other = q("SELECT job_posting_id::text, title FROM career.job_postings WHERE status='published' "
              "AND job_posting_id::text <> %s ORDER BY published_at DESC NULLS LAST LIMIT 1", published[0])
    state["browser_posting"] = {"id": other[0], "title": other[1]}

    def public_list():
        r = expect(c.get(f"{V1}/job-postings", params={"limit": 100}), 200).json()
        ids = [i["job_posting_id"] for i in r["items"]]
        assert JOBKOREA_DRAFT_ID not in ids and seed_draft not in ids
        statuses = {i.get("status") for i in r["items"]}
        return {"items": len(ids), "statuses": sorted(s for s in statuses if s)}
    rec.check("PUBLIC_POSTINGS", "D-anon", "anonymous public list returns 200 without draft rows", public_list)

    def jobkorea_hidden():
        r = expect(c.get(f"{V1}/job-postings", params={"q": JOBKOREA_DRAFT_MARK}), 200).json()
        assert r["items"] == [], r["items"][:1]
        d = c.get(f"{V1}/job-postings/{JOBKOREA_DRAFT_ID}")
        assert d.status_code == 404, d.status_code
        d2 = c.get(f"{V1}/job-postings/{JOBKOREA_DRAFT_ID}", headers=b)
        assert d2.status_code == 404, d2.status_code
        return {"search_items": 0, "detail_anon": d.status_code, "detail_logged_in": d2.status_code}
    rec.check("PUBLIC_POSTINGS", "D-anon", "JobKorea-like crawled draft fixture not searchable / detail 404", jobkorea_hidden)

    def seed_draft_hidden():
        d = c.get(f"{V1}/job-postings/{seed_draft}")
        assert d.status_code == 404, d.status_code
        return {"seed_draft_detail": d.status_code}
    rec.check("PUBLIC_POSTINGS", "D-anon", "synthetic seed draft posting detail 404", seed_draft_hidden)

    def published_detail():
        d = expect(c.get(f"{V1}/job-postings/{published[0]}"), 200).json()
        return {"detail": 200, "title": d["title"]}
    rec.check("PUBLIC_POSTINGS", "D-anon", "published posting detail 200", published_detail)

    # ------------------------------------------------------------------ COMPANY (API 조직, 비멤버·권한)
    org = {}

    def org_setup():
        r = expect(c.post(f"{V1}/organizations", headers=company, json={"name": "E2E API 조직"}), 201).json()
        org.update(r)
        assert r["status"] == "pending", r
        mine = expect(c.get(f"{V1}/me/organizations", headers=company), 200).json()
        role = [m["role"] for m in mine if m["organization"]["organization_id"] == r["organization_id"]]
        assert role == ["owner"], mine
        members = expect(c.get(f"{V1}/organizations/{r['organization_id']}/members", headers=company), 200).json()
        assert [m["role"] for m in members] == ["owner"]
        # 일반 사용자는 조직 승인 불가, 관리자 승인 → active
        expect(c.post(f"{V1}/admin/organizations/{r['organization_id']}/verification", headers=b,
                      json={"decision": "approve", "version": r["version"]}), 403)
        v = expect(c.post(f"{V1}/admin/organizations/{r['organization_id']}/verification", headers=admin2,
                          json={"decision": "approve", "version": r["version"]}), 200).json()
        assert v["status"] == "active"
        org.update(v)
        return {"org_status_after_register": "pending", "owner_role": "owner", "seeker_verify": 403,
                "admin_verify": v["status"]}
    rec.check("COMPANY", "B-org", "API register org (owner role) + admin verification (non-admin 403)", org_setup)
    state["api_org"] = org.get("organization_id")
    base = f"{V1}/organizations/{org.get('organization_id')}/postings"
    full = {"description": "E2E 합성 설명", "employment_type": "full_time", "location_text": "서울",
            "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat()}
    titles = {"draft": "E2EAPI-DRAFT 초안 공고", "pending": "E2EAPI-PENDING 검수중 공고",
              "rejected": "E2EAPI-REJECTED 반려 공고"}
    postings: dict = {}

    def company_postings():
        for key, title in titles.items():
            p = expect(c.post(base, headers=company, json={"title": title}), 201).json()
            if key != "draft":
                p = expect(c.patch(f"{base}/{p['posting_id']}", headers=company, json={**full, "version": p["version"]}),
                           200).json()
                p = expect(c.post(f"{base}/{p['posting_id']}/submit", headers=company, json={"version": p["version"]}),
                           200).json()
                assert p["status"] == "pending_review", p["status"]
            postings[key] = p
        return {k: v["status"] for k, v in postings.items()}
    rec.check("COMPANY", "B-postings", "API draft create/edit/submit (pending_review)", company_postings)
    state["api_postings"] = {k: v.get("posting_id") for k, v in postings.items()}

    def authz_outsider():
        out = {}
        out["outsider_list"] = c.get(base, headers=outsider).status_code
        out["outsider_create"] = c.post(base, headers=outsider, json={"title": "x"}).status_code
        out["outsider_get"] = c.get(f"{base}/{postings['draft']['posting_id']}", headers=outsider).status_code
        out["anon_list"] = c.get(base).status_code
        assert out["outsider_list"] == 404 and out["outsider_create"] == 404 and out["outsider_get"] == 404, out
        assert out["anon_list"] == 401, out
        return out
    rec.check("COMPANY", "B-authz", "non-member cannot list/create/read org postings (404), anonymous 401", authz_outsider)

    # ------------------------------------------------------------------ MODERATION 정책(PR #359 a93d8ae 병합 후)
    MC = f"{V1}/admin/moderation-cases"

    def cases_for(posting_id):
        return db.execute("SELECT case_id::text, status, version FROM career.moderation_cases WHERE "
                          "target_type='company_posting' AND target_id=%s ORDER BY created_at", (posting_id,)).fetchall()

    def snap(posting_id):
        post = q("SELECT status, version, public_posting_id FROM career.organization_job_postings WHERE posting_id=%s",
                 posting_id)
        return {"posting": [str(x) if x is not None else None for x in post], "cases": cases_for(posting_id),
                "job_postings": q("SELECT count(*) FROM career.job_postings")[0],
                "events": q("SELECT count(*) FROM career.moderation_case_events")[0]}

    def p1_submit_creates_one_case():
        got = {k: len(cases_for(postings[k]["posting_id"])) for k in ("pending", "rejected")}
        drafts = len(cases_for(postings["draft"]["posting_id"]))
        assert got == {"pending": 1, "rejected": 1} and drafts == 0, (got, drafts)
        st = cases_for(postings["pending"]["posting_id"])[0][1]
        assert st == "PENDING", st
        return {"cases_per_submitted_posting": got, "draft_cases": drafts, "status": st}
    rec.check("MODERATION", "policy", "P1 company submit creates exactly 1 moderation case (same transaction)",
              p1_submit_creates_one_case)

    def p2_failed_submit_rolls_back():
        incomplete = expect(c.post(base, headers=company, json={"title": "E2EAPI-INCOMPLETE 필수 누락"}), 201).json()
        r = c.post(f"{base}/{incomplete['posting_id']}/submit", headers=company, json={"version": incomplete["version"]})
        assert r.status_code == 422, (r.status_code, r.text[:200])
        after = q("SELECT status, version FROM career.organization_job_postings WHERE posting_id=%s",
                  incomplete["posting_id"])
        assert after == ("draft", incomplete["version"]) and cases_for(incomplete["posting_id"]) == [], after
        full_draft = expect(c.post(base, headers=company, json={"title": "E2EAPI-STALE 버전 충돌"}), 201).json()
        full_draft = expect(c.patch(f"{base}/{full_draft['posting_id']}", headers=company,
                                    json={**full, "version": full_draft["version"]}), 200).json()
        stale = c.post(f"{base}/{full_draft['posting_id']}/submit", headers=company,
                       json={"version": full_draft["version"] - 1}).status_code
        assert stale == 409 and cases_for(full_draft["posting_id"]) == [], stale
        postings["stale"] = full_draft
        return {"incomplete_submit": 422, "posting_after": list(after), "cases": 0, "stale_version_submit": stale}
    rec.check("MODERATION", "policy", "P2 failed submit (422 missing fields / 409 stale) → no case, posting unchanged",
              p2_failed_submit_rolls_back)

    def p3_concurrent_submit():
        from concurrent.futures import ThreadPoolExecutor
        p = postings["stale"]
        def go(_):
            with httpx.Client(base_url=api, timeout=60) as cc:
                return cc.post(f"{base}/{p['posting_id']}/submit", headers=company, json={"version": p["version"]}).status_code
        with ThreadPoolExecutor(max_workers=4) as pool:
            codes = sorted(pool.map(go, range(4)))
        open_cases = [r for r in cases_for(p["posting_id"]) if r[1] in ("PENDING", "IN_REVIEW")]
        assert codes.count(200) == 1 and len(open_cases) == 1, (codes, open_cases)
        return {"status_codes": codes, "open_cases": 1}
    rec.check("MODERATION", "policy", "P3 4 concurrent submits → one 200, one open case (no duplicate)",
              p3_concurrent_submit)

    def case_of(key):
        return cases_for(postings[key]["posting_id"])[0][0]

    def detail(case_id):
        return expect(c.get(f"{MC}/{case_id}", headers=admin2), 200).json()

    def p5_failed_approve_no_change():
        cid = case_of("pending")
        before = snap(postings["pending"]["posting_id"])
        d = detail(cid)
        unassigned = c.post(f"{MC}/{cid}/decision", headers=admin2, json={"version": d["version"], "decision": "APPROVE"})
        expect(c.post(f"{MC}/{cid}/assignment", headers=admin2, json={"version": d["version"]}), 200)
        d = detail(cid)
        stale = c.post(f"{MC}/{cid}/decision", headers=admin2, json={"version": d["version"] - 1, "decision": "APPROVE"})
        after = snap(postings["pending"]["posting_id"])
        assert unassigned.status_code in (409, 422) and stale.status_code == 409, (unassigned.status_code, stale.status_code)
        before_cmp = {**before, "cases": [r[:2] for r in before["cases"]], "events": None}
        after_cmp = {**after, "cases": [r[:2] for r in after["cases"]], "events": None}
        # 담당 시작으로 상태가 IN_REVIEW 가 된 것 외에는 공고·공개 행이 그대로여야 한다
        assert after["posting"] == before["posting"] and after["job_postings"] == before["job_postings"], (before, after)
        return {"approve_unassigned": unassigned.status_code, "approve_stale_version": stale.status_code,
                "posting_before_after": [before_cmp["posting"], after_cmp["posting"]],
                "public_rows_unchanged": after["job_postings"] == before["job_postings"]}
    rec.check("MODERATION", "policy", "P5 failed approve (unassigned / stale version) → posting & public rows unchanged",
              p5_failed_approve_no_change)

    def p7_direct_decision_cannot_publish():
        p = expect(c.get(f"{base}/{postings['pending']['posting_id']}", headers=company), 200).json()
        before = snap(p["posting_id"])
        admin_r = c.post(f"{V1}/admin/company-postings/{p['posting_id']}/decision", headers=admin2,
                         json={"decision": "approve", "version": p["version"]})
        seeker_r = c.post(f"{V1}/admin/company-postings/{p['posting_id']}/decision", headers=b,
                          json={"decision": "approve", "version": p["version"]})
        owner_r = c.post(f"{V1}/admin/company-postings/{p['posting_id']}/decision", headers=company,
                         json={"decision": "approve", "version": p["version"]})
        after = snap(p["posting_id"])
        assert admin_r.status_code == 409 and seeker_r.status_code == 403 and owner_r.status_code == 403, \
            (admin_r.status_code, seeker_r.status_code, owner_r.status_code)
        assert after["posting"] == before["posting"] and after["job_postings"] == before["job_postings"]
        assert after["posting"][0] == "pending_review" and after["posting"][2] is None
        return {"admin": admin_r.status_code, "seeker": seeker_r.status_code, "owner": owner_r.status_code,
                "posting_after": after["posting"], "public_rows_unchanged": True}
    rec.check("MODERATION", "policy", "P7 direct /admin/company-postings/{id}/decision cannot publish (admin 409, others 403)",
              p7_direct_decision_cannot_publish)

    def p8_non_admin_rejected():
        cid = case_of("pending")
        out = {"seeker_queue": c.get(MC, headers=b).status_code, "owner_queue": c.get(MC, headers=company).status_code,
               "seeker_detail": c.get(f"{MC}/{cid}", headers=b).status_code,
               "seeker_assign": c.post(f"{MC}/{cid}/assignment", headers=b, json={"version": 1}).status_code,
               "owner_decide": c.post(f"{MC}/{cid}/decision", headers=company,
                                      json={"version": 1, "decision": "APPROVE"}).status_code,
               "anon_queue": c.get(MC).status_code}
        assert out["anon_queue"] == 401 and all(v == 403 for k, v in out.items() if k != "anon_queue"), out
        perm = q("SELECT count(*) FROM career.role_permissions rp JOIN career.roles r USING (role_id) JOIN "
                 "career.permissions p USING (permission_id) WHERE r.code='admin' AND p.code='admin.content.review'")[0]
        return {**out, "admin_role_has_admin.content.review": perm}
    rec.check("MODERATION", "policy", "P8 non-admin (seeker, org owner) rejected on moderation API; anon 401",
              p8_non_admin_rejected)

    def p4_approve_publishes_and_closes():
        cid = case_of("pending")
        d = detail(cid)
        r = expect(c.post(f"{MC}/{cid}/decision", headers=admin2, json={"version": d["version"], "decision": "APPROVE"}),
                   200).json()
        assert r["status"] == "APPROVED", r["status"]
        row = q("SELECT o.status, jp.status, jp.source_id = (SELECT source_id FROM career.data_sources WHERE "
                "code='company_direct') FROM career.organization_job_postings o JOIN career.job_postings jp "
                "ON jp.job_posting_id=o.public_posting_id WHERE o.posting_id=%s", postings["pending"]["posting_id"])
        assert row == ("published", "published", True), row
        items = expect(c.get(f"{V1}/job-postings", params={"q": "E2EAPI-PENDING"}), 200).json()["items"]
        assert len(items) == 1, items
        again = c.post(f"{MC}/{cid}/decision", headers=admin2, json={"version": r["version"], "decision": "REJECT",
                                                                     "reason_code": "INACCURATE"}).status_code
        open_after = [x for x in cases_for(postings["pending"]["posting_id"]) if x[1] in ("PENDING", "IN_REVIEW")]
        assert again in (409, 422) and not open_after, (again, open_after)
        return {"case": r["status"], "posting/public/company_direct": row, "public_hits": 1,
                "second_decision": again, "open_cases_after": 0}
    rec.check("MODERATION", "policy", "P4 approve via moderation case → case APPROVED (closed), posting + public row published",
              p4_approve_publishes_and_closes)

    def p6_reject_stays_private():
        cid = case_of("rejected")
        d = detail(cid)
        expect(c.post(f"{MC}/{cid}/assignment", headers=admin2, json={"version": d["version"]}), 200)
        d = detail(cid)
        r = expect(c.post(f"{MC}/{cid}/decision", headers=admin2, json={"version": d["version"], "decision": "REJECT",
                                                                         "reason_code": "INACCURATE", "note": "E2E 반려"}),
                   200).json()
        own = expect(c.get(f"{base}/{postings['rejected']['posting_id']}", headers=company), 200).json()
        items = expect(c.get(f"{V1}/job-postings", params={"q": "E2EAPI-REJECTED"}), 200).json()["items"]
        assert r["status"] == "REJECTED" and own["status"] == "rejected" and own["public_posting_id"] is None, (r, own)
        assert items == []
        return {"case": r["status"], "posting": own["status"], "reason_code": own["reason_code"], "public_hits": 0}
    rec.check("MODERATION", "policy", "P6 reject via moderation case → posting rejected (reason visible to owner), not public",
              p6_reject_stays_private)

    def private_until_published():
        out = {}
        for key in ("draft", "rejected"):
            items = expect(c.get(f"{V1}/job-postings", params={"q": titles[key].split()[0]}), 200).json()["items"]
            out[key] = len(items)
        for key in ("draft", "rejected"):
            d = c.get(f"{V1}/job-postings", params={"q": titles[key].split()[0]}, headers=b).json()["items"]
            out[key + "_logged_in"] = len(d)
        assert all(v == 0 for v in out.values()), out
        return {"public_search_hits": out}
    rec.check("PUBLIC_POSTINGS", "D-anon", "company draft/rejected not in public list (anon + logged in)",
              private_until_published)

    def p9_jobkorea_private():
        st = q("SELECT status FROM career.job_postings WHERE job_posting_id=%s", JOBKOREA_DRAFT_ID)[0]
        cases = q("SELECT count(*) FROM career.moderation_cases WHERE target_id=%s", JOBKOREA_DRAFT_ID)[0]
        d = c.get(f"{V1}/job-postings/{JOBKOREA_DRAFT_ID}").status_code
        assert st == "draft" and d == 404, (st, d)
        return {"status_after_all_moderation": st, "detail": d, "cases": cases}
    rec.check("MODERATION", "policy", "P9 JobKorea-like crawled draft stays private after moderation flows",
              p9_jobkorea_private)

    # ------------------------------------------------------------------ NOTIFICATION / APPLICATION (B)
    def application_no_notification():
        before = q("SELECT count(*) FROM career.notification_deliveries WHERE user_id=%s",
                   accounts["seeker_b"]["user_id"])[0]
        app = expect(c.post(f"{V1}/me/job-applications", headers=b, json={"job_posting_id": published[0]}), 201).json()
        dup = c.post(f"{V1}/me/job-applications", headers=b, json={"job_posting_id": published[0]}).status_code
        up = expect(c.patch(f"{V1}/me/job-applications/{app['application_id']}", headers=b,
                            json={"version": app["version"], "stage": "applied"}), 200).json()
        stale = c.patch(f"{V1}/me/job-applications/{app['application_id']}", headers=b,
                        json={"version": app["version"], "stage": "interviewing"}).status_code
        idor = c.get(f"{V1}/me/job-applications/{app['application_id']}", headers=a).status_code
        after = q("SELECT count(*) FROM career.notification_deliveries WHERE user_id=%s",
                  accounts["seeker_b"]["user_id"])[0]
        inbox = expect(c.get(f"{V1}/me/notifications", headers=b), 200).json()
        assert dup == 409 and stale == 409 and idor == 404, (dup, stale, idor)
        assert after == before == 0, (before, after)
        state["seeker_b_application"] = app["application_id"]
        return {"create": 201, "duplicate": dup, "stage": up["stage"], "stale_version": stale, "other_user_get": idor,
                "notification_rows_before_after": [before, after], "inbox_items": len(inbox.get("items", []))}
    rec.check("NOTIFICATION", "A-application", "own stage change → no notification row (API + DB), 409/404 guards",
              application_no_notification)

    # ------------------------------------------------------------------ DOCUMENT (B, API)
    def document_lifecycle():
        r = expect(c.post(f"{V1}/documents", headers=b, data={"kind": "resume"},
                          files={"file": ("e2e-resume.pdf", pdf_bytes(), "application/pdf")}), 202).json()
        doc = r["document_id"]
        other = c.get(f"{V1}/documents/{doc}", headers=a).status_code
        out1 = worker("app.document_worker", env)
        st = expect(c.get(f"{V1}/documents/{doc}", headers=b), 200).json()["status"]
        f = expect(c.get(f"{V1}/documents/{doc}/file", headers=b), 200)
        assert f.content == pdf_bytes() and st == "ready" and other == 404, (st, other)
        expect(c.delete(f"{V1}/documents/{doc}", headers=b), 202)
        worker("app.document_worker", env)
        gone = c.get(f"{V1}/documents/{doc}", headers=b).status_code
        assert gone == 404
        return {"upload": 202, "after_worker": st, "download_bytes_equal": True, "other_user": other,
                "after_delete_worker": gone, "worker_stdout": out1}
    rec.check("DOCUMENT", "A-documents", "API upload → worker → ready → download → delete → worker → 404",
              document_lifecycle)

    # ------------------------------------------------------------------ PERSONAL DATA EXPORT (B, API + worker)
    def data_export():
        bad = c.post(f"{V1}/me/data-requests/reauth", headers=b, json={"password": "wrong-password-e2e"}).status_code
        no_token = c.post(f"{V1}/me/data-requests/exports", headers=b).status_code
        t = expect(c.post(f"{V1}/me/data-requests/reauth", headers=b, json={"password": password}), 200).json()
        rh = {**b, "X-Reauth-Token": t["reauth_token"]}
        req = expect(c.post(f"{V1}/me/data-requests/exports", headers=rh), 202).json()
        rid = req.get("request_id")
        out = worker("app.personal_data_worker", env)
        view = expect(c.get(f"{V1}/me/data-requests/exports/{rid}", headers=b), 200).json()
        other = c.get(f"{V1}/me/data-requests/exports/{rid}", headers=a).status_code
        link = expect(c.post(f"{V1}/me/data-requests/exports/{rid}/download-link", headers=rh), 201).json()
        dl = expect(c.post(f"{V1}/me/data-requests/download", headers=b, json={"token": link["token"]}), 200)
        again = c.post(f"{V1}/me/data-requests/download", headers=b, json={"token": link["token"]}).status_code
        body = dl.json()
        text = dl.text
        assert accounts["seeker_b"]["email"] in text, "export lacks own email"
        assert accounts["seeker"]["email"] not in text, "export leaks other user"
        assert other == 404 and again in (404, 422), (other, again)
        return {"wrong_password": bad, "without_reauth": no_token, "request": 202, "status_after_worker": view.get("status"),
                "worker": out, "other_user": other, "download": 200, "download_again": again,
                "top_level_keys": sorted(body)[:12] if isinstance(body, dict) else type(body).__name__}
    rec.check("USER", "A-data-export", "API reauth → export request → worker → one-time download (own data only)",
              data_export)

    # ------------------------------------------------------------------ PORTFOLIO (B, API)
    def portfolio():
        s = expect(c.get(f"{V1}/me/public-profile", headers=b), 200).json()["selection"]
        sel = expect(c.put(f"{V1}/me/public-profile/selection", headers=b, json={
            "fields": ["display_name", "headline", "experience.organization", "experience.title"],
            "experience_ids": [state["seeker_b_experience"]], "project_ids": [], "alias": None,
            "version": s["version"]}), 200).json()
        early = c.post(f"{V1}/me/public-profile/links", headers=b, json={"ttl_days": 7}).status_code
        expect(c.post(f"{V1}/me/public-profile/consent", headers=b, json={"version": sel["version"]}), 200)
        link = expect(c.post(f"{V1}/me/public-profile/links", headers=b, json={"ttl_days": 7}), 201).json()
        url = link.get("url") or ""
        token = url.rstrip("/").rsplit("/", 1)[-1]
        view = expect(c.get(f"{V1}/public/portfolios/{token}"), 200)
        vt = view.text
        assert "E2E 헤드라인" in vt and "서울" not in vt, "selection not honoured (location not selected)"
        assert accounts["seeker_b"]["email"] not in vt
        expect(c.delete(f"{V1}/me/public-profile/links/{link['link_id']}", headers=b), 204)
        revoked = c.get(f"{V1}/public/portfolios/{token}").status_code
        bogus = c.get(f"{V1}/public/portfolios/{'x' * 43}").status_code
        # 동의 철회 → 새 링크도 막힘
        link2 = expect(c.post(f"{V1}/me/public-profile/links", headers=b, json={"ttl_days": 7}), 201).json()
        token2 = link2["url"].rstrip("/").rsplit("/", 1)[-1]
        expect(c.get(f"{V1}/public/portfolios/{token2}"), 200)
        expect(c.delete(f"{V1}/me/public-profile/consent", headers=b), 204)
        withdrawn = c.get(f"{V1}/public/portfolios/{token2}").status_code
        non_consented = c.post(f"{V1}/me/public-profile/links", headers=outsider, json={"ttl_days": 7}).status_code
        assert revoked == 404 and withdrawn == 404 and bogus == 404, (revoked, withdrawn, bogus)
        assert early >= 400 and non_consented >= 400, (early, non_consented)
        return {"link_before_consent": early, "view": 200, "headers": {k: view.headers.get(k) for k in
                ("cache-control", "x-robots-tag")}, "after_revoke": revoked, "after_withdraw": withdrawn,
                "bogus_token": bogus, "non_consented_user_link": non_consented}
    rec.check("PORTFOLIO", "A/D-portfolio", "API selection→consent→link→anon view; revoke/withdraw/non-consent blocked",
              portfolio)

    c.close()
    db.close()
    return state
