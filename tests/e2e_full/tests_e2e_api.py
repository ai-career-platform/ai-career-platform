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

    def submit_case_count():
        n = q("SELECT count(*) FROM career.moderation_cases WHERE target_type='company_posting' AND target_id=%s",
              postings["pending"]["posting_id"])[0]
        return n
    try:
        n = submit_case_count()
        rec.add("MODERATION", "policy", "submit auto-creates exactly 1 moderation case (PR #359 pending)",
                "PASS" if n == 1 else "BLOCKED",
                {"observed_cases_for_submitted_posting": n, "expected_after_pr359": 1,
                 "note": "35fe589 does not auto-create cases on submit; depends on unmerged PR #359 commits"})
    except Exception as exc:  # noqa: BLE001
        rec.add("MODERATION", "policy", "submit auto-creates exactly 1 moderation case", "FAIL", str(exc))

    def non_admin_review():
        out = {"seeker_queue": c.get(f"{V1}/admin/company-postings", headers=b).status_code,
               "seeker_decision": c.post(f"{V1}/admin/company-postings/{postings['pending']['posting_id']}/decision",
                                         headers=b, json={"decision": "approve", "version": postings['pending']['version']}
                                         ).status_code,
               "owner_decision": c.post(f"{V1}/admin/company-postings/{postings['pending']['posting_id']}/decision",
                                        headers=company, json={"decision": "approve",
                                                               "version": postings['pending']['version']}).status_code,
               "seeker_moderation_queue": c.get(f"{V1}/admin/moderation-cases", headers=b).status_code,
               "anon_moderation_queue": c.get(f"{V1}/admin/moderation-cases").status_code}
        assert out["seeker_queue"] == 403 and out["seeker_decision"] == 403 and out["owner_decision"] == 403, out
        assert out["seeker_moderation_queue"] == 403 and out["anon_moderation_queue"] == 401, out
        st = q("SELECT status FROM career.organization_job_postings WHERE posting_id=%s",
               postings["pending"]["posting_id"])[0]
        assert st == "pending_review", st
        return {**out, "posting_status_after": st}
    rec.check("MODERATION", "C-authz", "non-admin (seeker, org owner) cannot review/decide; anon 401; state unchanged",
              non_admin_review)

    def api_reject():
        p = postings["rejected"]
        r = expect(c.post(f"{V1}/admin/company-postings/{p['posting_id']}/decision", headers=admin2,
                          json={"decision": "reject", "reason_code": "missing_required_info", "note": "E2E 반려",
                                "version": p["version"]}), 200).json()
        assert r["status"] == "rejected" and r["public_posting_id"] is None, r
        own = expect(c.get(f"{base}/{p['posting_id']}", headers=company), 200).json()
        assert own["status"] == "rejected" and own["reason_code"] == "missing_required_info"
        postings["rejected"] = own
        return {"status": own["status"], "reason_code": own["reason_code"], "public_posting_id": None}
    rec.check("COMPANY", "B-review", "admin reject (T126 decision) → owner sees rejected + reason; no public row",
              api_reject)

    def private_until_published():
        out = {}
        for key, title in titles.items():
            items = expect(c.get(f"{V1}/job-postings", params={"q": title.split()[0]}), 200).json()["items"]
            out[key] = len(items)
        assert out == {"draft": 0, "pending": 0, "rejected": 0}, out
        rows = q("SELECT count(*) FROM career.job_postings jp JOIN career.organization_public_companies opc "
                 "USING (company_id) WHERE opc.organization_id=%s", org["organization_id"])[0]
        assert rows == 0, rows
        return {"public_search_hits": out, "public_rows_for_org": rows}
    rec.check("PUBLIC_POSTINGS", "D-anon", "company draft/pending/rejected not in public list (no public row)",
              private_until_published)

    def direct_decision_probe():
        """정책(PR #359): /admin/company-postings/{id}/decision 으로는 게시할 수 없어야 한다. 현재 스택은 허용."""
        p = expect(c.get(f"{base}/{postings['pending']['posting_id']}", headers=company), 200).json()
        r = c.post(f"{V1}/admin/company-postings/{p['posting_id']}/decision", headers=admin2,
                   json={"decision": "approve", "version": p["version"]})
        published_now = r.status_code == 200 and r.json().get("status") == "published"
        return {"status_code": r.status_code, "published": published_now,
                "posting_status": (r.json().get("status") if r.status_code == 200 else r.json().get("code"))}
    try:
        ev = direct_decision_probe()
        rec.add("MODERATION", "policy", "direct /admin/company-postings/{id}/decision cannot publish (PR #359 pending)",
                "BLOCKED" if ev["published"] else "PASS",
                {**ev, "note": "at 35fe589 the T126 direct decision path is the documented approve path; PR #359 "
                               "is expected to route approval through moderation cases only"})
        state["direct_decision"] = ev
    except Exception as exc:  # noqa: BLE001
        rec.add("MODERATION", "policy", "direct decision probe", "FAIL", str(exc))

    def published_visible():
        ev = state.get("direct_decision") or {}
        if not ev.get("published"):
            return {"skipped": "not published"}
        items = expect(c.get(f"{V1}/job-postings", params={"q": "E2EAPI-PENDING"}), 200).json()["items"]
        assert len(items) == 1, items
        row = q("SELECT jp.status, jp.source_id = (SELECT source_id FROM career.data_sources WHERE code='company_direct') "
                "FROM career.organization_job_postings o JOIN career.job_postings jp ON jp.job_posting_id=o.public_posting_id "
                "WHERE o.posting_id=%s", postings["pending"]["posting_id"])
        assert row == ("published", True), row
        return {"public_hits": 1, "public_row": row}
    rec.check("PUBLIC_POSTINGS", "D-anon", "approved company posting appears publicly (company_direct source)",
              published_visible)

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
