import { useRef, useState, type FormEvent } from 'react';
import { TextField } from '../components/TextField';

export function FormPreview() {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [errors, setErrors] = useState<{
    name?: string;
    email?: string;
  }>({});
  const [message, setMessage] = useState('');
  const formRef = useRef<HTMLFormElement>(null);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage('');

    const nextErrors: typeof errors = {};

    if (!name.trim()) {
      nextErrors.name = '표시 이름을 입력해 주세요.';
    }

    const emailInput = formRef.current?.elements.namedItem('email');

    if (!email.trim()) {
      nextErrors.email = '이메일을 입력해 주세요.';
    } else if (
      emailInput instanceof HTMLInputElement &&
      emailInput.validity.typeMismatch
    ) {
      nextErrors.email = '올바른 이메일 형식으로 입력해 주세요.';
    }

    setErrors(nextErrors);

    if (Object.keys(nextErrors).length > 0) {
      const firstField = nextErrors.name ? 'displayName' : 'email';
      const field = formRef.current?.elements.namedItem(firstField);

      if (field instanceof HTMLInputElement) {
        field.focus();
      }

      return;
    }

    setMessage('입력 검증을 통과했습니다. 실제 서버에 저장되지는 않습니다.');
  }

  return (
    <form
      ref={formRef}
      onSubmit={handleSubmit}
      noValidate
      style={{ display: 'grid', gap: '24px', maxWidth: '480px' }}
    >
      <TextField
        label="표시 이름"
        name="displayName"
        value={name}
        onChange={(event) => setName(event.target.value)}
        required
        autoComplete="nickname"
        error={errors.name}
      />

      <TextField
        label="이메일"
        name="email"
        type="email"
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        required
        autoComplete="email"
        error={errors.email}
      />

      <button type="submit" className="state-panel-action">
        입력 확인
      </button>

      <p role="status">{message}</p>
    </form>
  );
}
