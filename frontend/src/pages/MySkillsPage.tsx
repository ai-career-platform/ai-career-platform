/**
 * UI-008 나의 기술 (T34, FR-PRF-001). API: T33 GET/PUT /v1/me/skills, T17 GET /v1/skills.
 *
 * - 기술은 검색 목록에서만 고를 수 있다(목록에 없는 기술 직접 입력 불가).
 * - 같은 기술은 한 번만 추가된다.
 * - 숙련도는 1~5 또는 미입력. 자기평가이며 AI 분석 수치가 아니다.
 * - 화면에서 고친 내용은 "저장"을 눌러야 한 번에 반영된다(PUT 전체 교체).
 *   저장에 실패하면 서버 데이터는 그대로이고, 화면의 수정 내용은 유지해 다시 시도하거나 되돌릴 수 있다.
 */
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { ApiError } from '../api/client';
import { useApi } from '../api/ApiContext';
import {
  MAX_SKILLS, SEARCH_MAX_LENGTH, SEARCH_MIN_LENGTH, proficiencyLabels,
  type Proficiency, type Skill, type UserSkill,
} from '../api/skills';
import { Button } from '../components/Button';
import { StatePanel } from '../components/StatePanel';
import { env } from '../config/env';
import './MySkillsPage.css';

const SEARCH_DELAY_MS = 250;
const levels = [1, 2, 3, 4, 5] as const;

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    if (error.status === 0) return '서버에 연결하지 못했습니다. 네트워크 상태를 확인해 주세요.';
    if (error.userMessage) return error.userMessage;
  }
  return fallback;
}

const sameSkills = (a: UserSkill[], b: UserSkill[]) =>
  a.length === b.length && a.every((x, i) => x.skill.skill_id === b[i]!.skill.skill_id && x.proficiency === b[i]!.proficiency);

export function MySkillsPage() {
  const api = useApi();
  const [saved, setSaved] = useState<UserSkill[]>([]);
  const [draft, setDraft] = useState<UserSkill[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  const [query, setQuery] = useState('');
  const [search, setSearch] = useState<{ q: string; items: Skill[]; failed: boolean }>({ q: '', items: [], failed: false });
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [hint, setHint] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const listboxId = useId();
  const inputId = useId();

  const load = useCallback(() => api.me.skills.list().then(
    list => { setSaved(list); setDraft(list); setLoadError(''); },
    e => { setLoadError(errorMessage(e, '내 기술을 불러오지 못했습니다.')); },
  ).finally(() => setLoading(false)), [api]);

  useEffect(() => { void load(); }, [load]);

  function retry() { setLoading(true); setLoadError(''); void load(); }

  const trimmed = query.trim();
  const searchable = trimmed.length >= SEARCH_MIN_LENGTH;
  useEffect(() => {
    if (!searchable) return undefined;
    // 검색어가 바뀌면 이전 요청은 폐기한다. 이미 보낸 요청이 늦게 돌아와도(성공·실패 모두) 상태를 덮어쓰지 않는다.
    const obsolete = new AbortController();
    const timer = setTimeout(() => {
      api.skills.search({ q: trimmed, limit: 10 }, obsolete.signal).then(
        r => {
          if (obsolete.signal.aborted) return;
          setSearch({ q: trimmed, items: r.items, failed: false }); setActive(r.items.length ? 0 : -1);
        },
        () => { if (!obsolete.signal.aborted) setSearch({ q: trimmed, items: [], failed: true }); },
      );
    }, SEARCH_DELAY_MS);
    return () => { clearTimeout(timer); obsolete.abort(); };
  }, [api, trimmed, searchable]);
  const current = search.q === trimmed ? search : null;
  const results = current?.items ?? [];
  const searchStatus: 'idle' | 'loading' | 'done' | 'error' =
    !searchable ? 'idle' : !current ? 'loading' : current.failed ? 'error' : 'done';

  const owned = useMemo(() => new Set(draft.map(s => s.skill.skill_id)), [draft]);
  const dirty = !sameSkills(draft, saved);
  const full = draft.length >= MAX_SKILLS;

  function add(skill: Skill) {
    // 저장 중에 추가하면 PUT 응답으로 목록을 바꿀 때 사라지므로 막는다
    if (saving) return;
    setNotice(''); setError('');
    if (owned.has(skill.skill_id)) { setHint(`${skill.name}은(는) 이미 추가한 기술입니다.`); return; }
    if (full) { setHint(`기술은 최대 ${MAX_SKILLS}개까지 등록할 수 있습니다.`); return; }
    setDraft(d => [...d, { skill, proficiency: null }]);
    setHint(`${skill.name}을(를) 추가했습니다. 숙련도를 고른 뒤 저장해 주세요.`);
    setQuery(''); setOpen(false); setActive(-1);
    inputRef.current?.focus();
  }

  function onSearchKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (!results.length) return;
      e.preventDefault(); setOpen(true);
      setActive(i => (i + (e.key === 'ArrowDown' ? 1 : -1) + results.length) % results.length);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (saving) return;
      const pick = open && active >= 0 ? results[active] : undefined;
      if (pick) add(pick);
      else if (searchable) setHint('목록에 있는 기술만 추가할 수 있습니다. 검색 결과에서 골라 주세요.');
    } else if (e.key === 'Escape') {
      setOpen(false); setActive(-1);
    }
  }

  const setLevel = (id: string, value: string) => {
    setNotice('');
    setDraft(d => d.map(s => s.skill.skill_id === id ? { ...s, proficiency: value ? Number(value) as Proficiency : null } : s));
  };
  const remove = (skill: Skill) => {
    setNotice(''); setDraft(d => d.filter(s => s.skill.skill_id !== skill.skill_id));
    setHint(`${skill.name}을(를) 목록에서 뺐습니다. 저장해야 반영됩니다.`);
  };

  async function save() {
    if (saving || !dirty) return;
    setSaving(true); setError(''); setNotice('');
    try {
      const result = await api.me.skills.replace({
        items: draft.map(s => ({ skill_id: s.skill.skill_id, proficiency: s.proficiency })),
      });
      setSaved(result); setDraft(result); setHint('');
      setNotice('저장했습니다.');
    } catch (e) {
      setError(`${errorMessage(e, '저장하지 못했습니다.')} 저장되지 않았고, 화면의 수정 내용은 그대로 남아 있습니다.`);
    } finally { setSaving(false); }
  }

  function revert() { setDraft(saved); setError(''); setHint(''); setNotice('저장된 상태로 되돌렸습니다.'); }

  const showList = open && searchable && !saving;
  const activeId = showList && active >= 0 && results[active] ? `${listboxId}-${results[active]!.skill_id}` : undefined;

  return <section className="skills-page" aria-labelledby="skills-title">
    <h1 id="skills-title">나의 기술</h1>
    <p className="skills-lead">보유 기술과 숙련도를 등록하면 목표 직무와 비교해 부족한 기술을 알려 드립니다.</p>
    {env.mockEnabled && <p className="skills-mode" role="status">Mock 모드: 가상 기술 목록이며 실제 PostgreSQL 저장이 아닙니다.</p>}

    {loading ? <StatePanel variant="loading" title="내 기술을 불러오는 중" />
      : loadError ? <StatePanel variant="error" title="내 기술을 불러오지 못했습니다" description={loadError}
        actionLabel="다시 시도" onAction={retry} />
      : <>
        <div className="skills-search">
          <label htmlFor={inputId}>기술 검색</label>
          <p id={`${inputId}-hint`} className="skills-hint">{SEARCH_MIN_LENGTH}글자 이상 입력한 뒤 목록에서 골라 주세요. 화살표 키로 이동, Enter로 추가합니다.</p>
          <input id={inputId} ref={inputRef} type="search" role="combobox" autoComplete="off"
            maxLength={SEARCH_MAX_LENGTH} value={query} disabled={saving || full}
            aria-expanded={showList} aria-controls={listboxId} aria-autocomplete="list"
            aria-activedescendant={activeId} aria-describedby={`${inputId}-hint`}
            onChange={e => { setQuery(e.target.value); setOpen(true); setHint(''); }}
            onFocus={() => setOpen(true)} onKeyDown={onSearchKeyDown} />
          {showList && <ul id={listboxId} role="listbox" aria-label="기술 검색 결과" className="skills-results">
            {searchStatus === 'loading' && <li role="presentation" className="skills-results-note">검색 중…</li>}
            {searchStatus === 'error' && <li role="presentation" className="skills-results-note">검색하지 못했습니다. 잠시 후 다시 시도해 주세요.</li>}
            {searchStatus === 'done' && results.length === 0 && <li role="presentation" className="skills-results-note">검색 결과가 없습니다. 다른 이름으로 찾아보세요.</li>}
            {searchStatus === 'done' && results.map((skill, i) => {
              const already = owned.has(skill.skill_id);
              return <li key={skill.skill_id} id={`${listboxId}-${skill.skill_id}`} role="option"
                aria-selected={i === active} aria-disabled={already}
                className={i === active ? 'is-active' : undefined}
                onMouseDown={e => e.preventDefault()} onClick={() => add(skill)}>
                {skill.name} {already && <span className="skills-tag">추가됨</span>}
              </li>;
            })}
          </ul>}
          <p className="skills-live" role="status" aria-live="polite">{hint}</p>
        </div>

        <h2>등록한 기술 <span className="skills-count">{draft.length} / {MAX_SKILLS}</span></h2>
        <p className="skills-hint">숙련도는 직접 고르는 <strong>자기평가</strong>이며 AI 분석 수치가 아닙니다. 비워 두면 Skill Gap 계산 때 0으로 계산하고 "숙련도 미입력"으로 표시합니다.</p>
        {draft.length === 0
          ? <StatePanel variant="empty" title="등록한 기술이 없습니다" description="기술을 1개 이상 등록하면 분석을 받을 수 있습니다." />
          : <ul className="skills-list" aria-label="등록한 기술">
            {draft.map(({ skill, proficiency }) => <li key={skill.skill_id} className="skills-row">
              <span className="skills-name">{skill.name}{proficiency === null && <span className="skills-tag">숙련도 미입력</span>}</span>
              <label className="skills-level">
                <span className="visually-hidden">{skill.name} 숙련도</span>
                <select value={proficiency ?? ''} disabled={saving} onChange={e => setLevel(skill.skill_id, e.target.value)}>
                  <option value="">미입력</option>
                  {levels.map(l => <option key={l} value={l}>{l} · {proficiencyLabels[l]}</option>)}
                </select>
              </label>
              <Button variant="outline" disabled={saving} aria-label={`${skill.name} 삭제`} onClick={() => remove(skill)}>삭제</Button>
            </li>)}
          </ul>}

        {error && <p className="skills-error" role="alert">{error}</p>}
        {notice && <p className="skills-notice" role="status">{notice}</p>}
        <div className="skills-actions">
          <Button onClick={() => void save()} disabled={!dirty || saving}>{saving ? '저장 중…' : '저장'}</Button>
          {dirty && <Button variant="outline" disabled={saving} onClick={revert}>저장된 상태로 되돌리기</Button>}
          {dirty && !saving && <span className="skills-dirty">저장하지 않은 변경이 있습니다.</span>}
        </div>
      </>}
  </section>;
}
