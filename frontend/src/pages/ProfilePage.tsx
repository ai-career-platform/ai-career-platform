import { useCallback, useEffect, useId, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { ApiError } from '../api/client';
import { useAuth } from '../auth/useAuth';
import { Button } from '../components/Button';
import { StatePanel } from '../components/StatePanel';
import { TextField } from '../components/TextField';
import { BackIcon, MailIcon, NoteIcon, PencilIcon, PinIcon, QuoteIcon, UserIcon } from './profileIcons';
import './ProfilePage.css';

interface Me {
  email: string;
  display_name: string;
  profile: { headline: string | null; bio: string | null; location_text: string | null };
}

/** 폼 값. 서버의 null 은 빈 문자열로 보여주고, 저장할 때 다시 null 로 보냅니다. */
interface FormValues {
  display_name: string;
  headline: string;
  bio: string;
  location_text: string;
}
type FieldName = keyof FormValues;
type FieldErrors = Partial<Record<FieldName, string>>;

// 최대 길이는 T16 API(MePatch)와 같습니다. 서버 422 에는 필드 정보가 없어 화면에서 먼저 검사합니다.
const FIELDS: { name: FieldName; label: string; max: number; multiline?: boolean; required?: boolean }[] = [
  { name: 'display_name', label: '이름', max: 100, required: true },
  { name: 'headline', label: '한 줄 소개', max: 200 },
  { name: 'bio', label: '자기소개', max: 5000, multiline: true },
  { name: 'location_text', label: '희망·거주 지역', max: 120 },
];

const toForm = (me: Me): FormValues => ({
  display_name: me.display_name,
  headline: me.profile.headline ?? '',
  bio: me.profile.bio ?? '',
  location_text: me.profile.location_text ?? '',
});

function validate(values: FormValues): FieldErrors {
  const errors: FieldErrors = {};
  for (const { name, max, required } of FIELDS) {
    if (required && values[name].trim() === '') errors[name] = '필수 입력 항목입니다.';
    else if (values[name].length > max) errors[name] = `최대 ${max}자까지 입력할 수 있습니다.`;
  }
  return errors;
}

const VIEW_ROWS = [
  { name: 'display_name', label: '이름', icon: <UserIcon /> },
  { name: 'headline', label: '한 줄 소개', icon: <QuoteIcon /> },
  { name: 'bio', label: '자기소개', icon: <NoteIcon /> },
  { name: 'location_text', label: '희망·거주 지역', icon: <PinIcon /> },
] as const;

/** 연한 파란 곡선 배경과 이름 첫 글자 아바타. 프로필 사진 API 가 없어 사진 업로드는 두지 않습니다. */
function ProfileHeader({ title, name, left, right }: { title: string; name: string; left?: ReactNode; right?: ReactNode }) {
  return (
    <header className="profile-hero">
      <div className="profile-hero-bar">
        <span className="profile-hero-side">{left}</span>
        <h1 id="profile-title">{title}</h1>
        <span className="profile-hero-side profile-hero-side--right">{right}</span>
      </div>
      <div className="profile-avatar" aria-hidden="true">
        {name.trim().charAt(0) || '?'}
      </div>
    </header>
  );
}

/** TextField 와 같은 모양의 여러 줄 입력 (T20 TextField 는 한 줄 입력만 지원). */
function TextArea({ label, error, ...props }: { label: string; error?: string } & React.ComponentPropsWithoutRef<'textarea'>) {
  const id = useId();
  const errorId = `${id}-error`;
  return (
    <div className="text-field">
      <label className="text-field-label" htmlFor={id}>
        {label}
      </label>
      <textarea
        {...props}
        id={id}
        rows={6}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        className="text-field-input profile-textarea"
      />
      {error && (
        <p id={errorId} className="text-field-error">
          {error}
        </p>
      )}
    </div>
  );
}

/** 내 프로필 보기·수정 화면 (UI-003). 항상 로그인한 본인의 /me 만 다루고 사용자 ID 는 받지 않습니다. */
export function ProfilePage() {
  const { request, updateUser } = useAuth();
  const [email, setEmail] = useState('');
  const [saved, setSaved] = useState<FormValues | null>(null);
  const [values, setValues] = useState<FormValues | null>(null);
  const [editing, setEditing] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});

  const apply = useCallback((me: Me) => {
    const form = toForm(me);
    setEmail(me.email);
    setSaved(form);
    setValues(form);
    setLoadFailed(false);
  }, []);

  useEffect(() => {
    let cancelled = false;
    request<Me>('/v1/me')
      .then((me) => !cancelled && apply(me))
      .catch(() => !cancelled && setLoadFailed(true));
    return () => {
      cancelled = true;
    };
  }, [request, apply]);

  if (loadFailed) {
    return (
      <section aria-labelledby="profile-title" className="profile-page">
        <ProfileHeader title="내 프로필" name="" />
        <div className="profile-body">
          <StatePanel
            variant="error"
            title="프로필을 불러오지 못했습니다"
            actionLabel="다시 시도"
            onAction={() => {
              setLoadFailed(false);
              request<Me>('/v1/me').then(apply, () => setLoadFailed(true));
            }}
          />
        </div>
      </section>
    );
  }
  if (!saved || !values) {
    return (
      <section aria-labelledby="profile-title" className="profile-page">
        <ProfileHeader title="내 프로필" name="" />
        <div className="profile-body">
          <StatePanel variant="loading" title="프로필을 불러오는 중입니다" />
        </div>
      </section>
    );
  }

  const change = (name: FieldName, value: string) => {
    setValues({ ...values, [name]: value });
    setMessage(null);
  };

  const cancelEdit = () => {
    setValues(saved);
    setFieldErrors({});
    setMessage(null);
    setEditing(false);
  };

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!saved || !values) return;

    const invalid = validate(values);
    setFieldErrors(invalid);
    if (Object.keys(invalid).length > 0) {
      setMessage({ kind: 'error', text: '입력한 내용을 확인해 주세요.' });
      return;
    }

    // PATCH 는 바뀐 필드만 보내고, 비운 선택 항목은 null 로 보내 값을 지웁니다.
    const patch: Record<string, string | null> = {};
    for (const { name } of FIELDS) {
      if (values[name] !== saved[name]) patch[name] = name === 'display_name' ? values[name] : values[name] || null;
    }
    if (Object.keys(patch).length === 0) {
      setMessage({ kind: 'ok', text: '변경된 내용이 없습니다.' });
      return;
    }

    setSaving(true);
    try {
      await request('/v1/me', { method: 'PATCH', body: patch });
      const fresh = await request<Me>('/v1/me'); // 저장 후 서버 값으로 다시 조회
      apply(fresh);
      updateUser({ displayName: fresh.display_name });
      setEditing(false);
      setMessage({ kind: 'ok', text: '프로필을 저장했습니다.' });
    } catch (error) {
      if (error instanceof ApiError && error.status === 422) {
        // 서버의 422 에는 필드 정보가 없어(code·status·message 뿐) 공통 안내만 보여줍니다. 항목별 안내는 화면 검사가 맡습니다.
        setMessage({ kind: 'error', text: '입력한 내용을 확인해 주세요.' });
      } else if (!(error instanceof ApiError && error.status === 401)) {
        // 401 은 세션 만료로 보호 경로 가드가 로그인 화면으로 보냅니다.
        setMessage({ kind: 'error', text: '저장하지 못했습니다. 잠시 후 다시 시도해 주세요.' });
      }
    } finally {
      setSaving(false);
    }
  }

  const messageEl = message && (
    <p role={message.kind === 'error' ? 'alert' : 'status'} className={`profile-message profile-message--${message.kind}`}>
      {message.text}
    </p>
  );

  if (!editing) {
    return (
      <section aria-labelledby="profile-title" className="profile-page">
        <ProfileHeader
          title="내 프로필"
          name={saved.display_name}
          right={
            <button
              type="button"
              className="profile-icon-button"
              aria-label="프로필 수정"
              onClick={() => {
                setMessage(null);
                setEditing(true);
              }}
            >
              <PencilIcon />
            </button>
          }
        />
        <div className="profile-body">
          {messageEl}
          <dl className="profile-rows">
            {VIEW_ROWS.map(({ name, label, icon }) => (
              <div key={name} className="profile-row">
                <span className="profile-row-icon">{icon}</span>
                <div className="profile-row-text">
                  <dt>{label}</dt>
                  <dd className={saved[name] ? undefined : 'profile-row-empty'}>{saved[name] || '입력하지 않았어요'}</dd>
                </div>
              </div>
            ))}
            <div className="profile-row">
              <span className="profile-row-icon">
                <MailIcon />
              </span>
              <div className="profile-row-text">
                <dt>이메일</dt>
                <dd>{email}</dd>
              </div>
            </div>
          </dl>
        </div>
      </section>
    );
  }

  return (
    <section aria-labelledby="profile-title" className="profile-page">
      <ProfileHeader
        title="프로필 수정"
        name={saved.display_name}
        left={
          <button type="button" className="profile-icon-button" aria-label="뒤로" disabled={saving} onClick={cancelEdit}>
            <BackIcon />
          </button>
        }
      />
      <div className="profile-body">
        <form onSubmit={onSubmit} noValidate className="profile-form">
          {FIELDS.map(({ name, label, multiline, required }) =>
            multiline ? (
              <TextArea
                key={name}
                label={label}
                name={name}
                value={values[name]}
                error={fieldErrors[name]}
                onChange={(e) => change(name, e.target.value)}
              />
            ) : (
              <TextField
                key={name}
                label={label}
                name={name}
                required={required}
                value={values[name]}
                error={fieldErrors[name]}
                onChange={(e) => change(name, e.target.value)}
              />
            ),
          )}
          {messageEl}
          <div className="profile-actions">
            <Button type="submit" disabled={saving}>
              {saving ? '저장 중…' : '저장'}
            </Button>
            <Button variant="outline" disabled={saving} onClick={cancelEdit}>
              취소
            </Button>
          </div>
        </form>
      </div>
    </section>
  );
}
