/**
 * UI-008 나의 기술 (T34, FR-PRF-001). API: T33 GET/PUT /v1/me/skills, T17 GET /v1/skills.
 * T140: VITE_SKILL_AUTOCOMPLETE=true 이면 T139 GET /v1/skills/suggest(동의어 → 표준 코드, PROPOSED)로 찾습니다.
 *   - 한글 IME 조합 중(isComposing)의 Enter·화살표는 무시합니다(조합 확정용 Enter 로 기술이 추가되지 않게).
 *   - 다의어(ambiguous)는 후보를 모두 보여 주고 사용자가 고릅니다. 등록할 수 없는(skill_id 없음) 코드는 고를 수 없습니다.
 *
 * - 기술은 검색 목록에서만 고를 수 있다(목록에 없는 기술 직접 입력 불가).
 * - 같은 기술은 한 번만 추가된다.
 * - 숙련도는 1~5 또는 미입력. 자기평가이며 AI 분석 수치가 아니다.
 * - 화면에서 고친 내용은 "저장"을 눌러야 한 번에 반영된다(PUT 전체 교체).
 *   저장에 실패하면 서버 데이터는 그대로이고, 화면의 수정 내용은 유지해 다시 시도하거나 되돌릴 수 있다.
 */
import { useId, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { ApiError } from '../api/client';
import { useApi } from '../api/ApiContext';
import { useQuery } from '../api/useQuery';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import {
  MAX_SKILLS, SEARCH_MAX_LENGTH, SEARCH_MIN_LENGTH, normalizeSkillTerm, proficiencyLabels,
  type Proficiency, type Skill, type SkillSuggestion, type UserSkill,
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

/** 검색 결과 한 줄. skill 이 null 이면 고를 수 없는 항목입니다(T139 skill_id 없음). */
interface SearchOption { key: string; name: string; skill: Skill | null; note?: string }

const fromSkill = (skill: Skill): SearchOption => ({ key: skill.skill_id, name: skill.name, skill });
function fromSuggestion(s: SkillSuggestion): SearchOption {
  const skill = s.skill_id ? { skill_id: s.skill_id, code: s.code, name: s.name } : null;
  const note = !skill ? '아직 등록할 수 없는 기술'
    : s.match_type === 'alias' ? `‘${s.matched}’로 찾음`
    : s.match_type === 'ambiguous' ? `‘${s.matched}’: 여러 기술 중 골라 주세요`
    // 동의어 앞부분·일부로 찾은 경우(예: '리액' → 리액트) 어떤 표기로 찾았는지 보여 준다
    : s.matched !== s.code && normalizeSkillTerm(s.matched) !== normalizeSkillTerm(s.name) ? `‘${s.matched}’` : undefined;
  return { key: s.code, name: s.name, skill, note };
}

const sameSkills = (a: UserSkill[], b: UserSkill[]) =>
  a.length === b.length && a.every((x, i) => x.skill.skill_id === b[i]!.skill.skill_id && x.proficiency === b[i]!.proficiency);

export function MySkillsPage() {
  const api = useApi();
  const mine = useQuery(['me-skills'], (signal) => api.me.skills.list(signal));
  const saved = useMemo(() => (mine.status === 'ready' ? mine.data : []), [mine]);
  // 화면에서 고친 목록(저장 전). null 이면 서버에 저장된 목록을 그대로 보여 줍니다.
  const [edits, setEdits] = useState<UserSkill[] | null>(null);
  const draft = edits ?? saved;
  const setDraft = (update: (current: UserSkill[]) => UserSkill[]) => setEdits((e) => update(e ?? saved));
  const loading = mine.status === 'loading';
  const loadError = mine.status === 'error' ? errorMessage(mine.error, '내 기술을 불러오지 못했습니다.') : '';
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [hint, setHint] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const composing = useRef(false);
  const suggestMode = env.skillAutocomplete;
  const listboxId = useId();
  const inputId = useId();

  const trimmed = query.trim();
  // T139 는 정규화 후 1글자부터(한글 한 음절도 의미가 있음), T17 은 2글자부터
  const searchable = suggestMode ? normalizeSkillTerm(trimmed).length >= 1 : trimmed.length >= SEARCH_MIN_LENGTH;
  // 입력이 SEARCH_DELAY_MS 동안 멈추면 검색합니다. 검색어가 바뀌면 useQuery 가 이전 요청을 취소하고,
  // 늦게 돌아온 이전 응답(성공·실패 모두)은 화면을 덮어쓰지 않습니다.
  const settledQuery = useDebouncedValue(trimmed, SEARCH_DELAY_MS);
  const found = useQuery(searchable && settledQuery === trimmed && ['skill-search', suggestMode, trimmed], async (signal) => {
    const options = suggestMode
      ? (await api.skills.suggest({ q: trimmed, limit: 10 }, signal)).items.map(fromSuggestion)
      : (await api.skills.search({ q: trimmed, limit: 10 }, signal)).items.map(fromSkill);
    if (!signal.aborted) setActive(options.length ? 0 : -1);
    return options;
  });
  const results: SearchOption[] = found.status === 'ready' ? found.data : [];
  const searchStatus: 'idle' | 'loading' | 'done' | 'error' =
    !searchable ? 'idle' : found.status === 'error' ? 'error' : found.status === 'ready' ? 'done' : 'loading';

  const owned = useMemo(() => new Set(draft.map(s => s.skill.skill_id)), [draft]);
  const dirty = !sameSkills(draft, saved);
  const full = draft.length >= MAX_SKILLS;

  function add(option: SearchOption) {
    // 저장 중에 추가하면 PUT 응답으로 목록을 바꿀 때 사라지므로 막는다
    if (saving) return;
    setNotice(''); setError('');
    const skill = option.skill;
    if (!skill) { setHint(`${option.name}은(는) 아직 등록할 수 있는 기술 목록에 없습니다. 다른 기술을 골라 주세요.`); return; }
    if (owned.has(skill.skill_id)) { setHint(`${skill.name}은(는) 이미 추가한 기술입니다.`); return; }
    if (full) { setHint(`기술은 최대 ${MAX_SKILLS}개까지 등록할 수 있습니다.`); return; }
    setDraft(d => [...d, { skill, proficiency: null }]);
    setHint(`${skill.name}을(를) 추가했습니다. 숙련도를 고른 뒤 저장해 주세요.`);
    setQuery(''); setOpen(false); setActive(-1);
    inputRef.current?.focus();
  }

  function onSearchKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    // 한글 조합 중 키(조합 확정 Enter 등)는 목록 조작으로 쓰지 않는다. keyCode 229 는 일부 브라우저의 조합 중 표시.
    if (e.nativeEvent.isComposing || composing.current || e.keyCode === 229) return;
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
      mine.setData(() => result); setEdits(null); setHint('');
      setNotice('저장했습니다.');
    } catch (e) {
      setError(`${errorMessage(e, '저장하지 못했습니다.')} 저장되지 않았고, 화면의 수정 내용은 그대로 남아 있습니다.`);
    } finally { setSaving(false); }
  }

  function revert() { setEdits(null); setError(''); setHint(''); setNotice('저장된 상태로 되돌렸습니다.'); }

  const showList = open && searchable && !saving;
  const optionId = (o: SearchOption) => `${listboxId}-${o.key}`;
  const activeId = showList && active >= 0 && results[active] ? optionId(results[active]!) : undefined;

  return <section className="skills-page" aria-labelledby="skills-title">
    <h1 id="skills-title">나의 기술</h1>
    <p className="skills-lead">보유 기술과 숙련도를 등록하면 목표 직무와 비교해 부족한 기술을 알려 드립니다.</p>
    {env.mockEnabled && <p className="skills-mode" role="status">Mock 모드: 가상 기술 목록이며 실제 PostgreSQL 저장이 아닙니다.</p>}

    {loading ? <StatePanel variant="loading" title="내 기술을 불러오는 중" />
      : loadError ? <StatePanel variant="error" title="내 기술을 불러오지 못했습니다" description={loadError}
        actionLabel="다시 시도" onAction={mine.retry} />
      : <>
        <div className="skills-search">
          <label htmlFor={inputId}>기술 검색</label>
          <p id={`${inputId}-hint`} className="skills-hint">{suggestMode
            ? '한글·영문 이름이나 줄임말(예: 파이썬, k8s)로 찾은 뒤 목록에서 골라 주세요. 화살표 키로 이동, Enter로 추가, Esc로 닫습니다.'
            : `${SEARCH_MIN_LENGTH}글자 이상 입력한 뒤 목록에서 골라 주세요. 화살표 키로 이동, Enter로 추가합니다.`}</p>
          <input id={inputId} ref={inputRef} type="search" role="combobox" autoComplete="off"
            maxLength={SEARCH_MAX_LENGTH} value={query} disabled={saving || full}
            aria-expanded={showList} aria-controls={listboxId} aria-autocomplete="list"
            aria-activedescendant={activeId} aria-describedby={`${inputId}-hint`}
            onChange={e => { setQuery(e.target.value); setOpen(true); setHint(''); }}
            onFocus={() => setOpen(true)} onKeyDown={onSearchKeyDown}
            onCompositionStart={() => { composing.current = true; }}
            onCompositionEnd={() => { composing.current = false; }} />
          {showList && <ul id={listboxId} role="listbox" aria-label="기술 검색 결과" className="skills-results">
            {searchStatus === 'loading' && <li role="presentation" className="skills-results-note">검색 중…</li>}
            {searchStatus === 'error' && <li role="presentation" className="skills-results-note">검색하지 못했습니다. 잠시 후 다시 시도해 주세요.</li>}
            {searchStatus === 'done' && results.length === 0 && <li role="presentation" className="skills-results-note">검색 결과가 없습니다. 다른 이름으로 찾아보세요.</li>}
            {searchStatus === 'done' && results.map((option, i) => {
              const already = option.skill !== null && owned.has(option.skill.skill_id);
              return <li key={option.key} id={optionId(option)} role="option"
                aria-selected={i === active} aria-disabled={already || option.skill === null}
                className={i === active ? 'is-active' : undefined}
                onMouseDown={e => e.preventDefault()} onClick={() => add(option)}>
                {option.name} {option.note && <span className="skills-note">{option.note}</span>}
                {already && <span className="skills-tag">추가됨</span>}
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
