import { useId, type ComponentPropsWithoutRef } from 'react';
import './TextField.css';

type TextFieldProps = ComponentPropsWithoutRef<'input'> & {
  label: string;
  hint?: string;
  error?: string;
};

export function TextField({
  label,
  hint,
  error,
  id,
  required,
  className,
  'aria-describedby': describedBy,
  'aria-invalid': ariaInvalid,
  ...inputProps
}: TextFieldProps) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const hintId = `${inputId}-hint`;
  const errorId = `${inputId}-error`;

  const descriptionIds = [
    describedBy,
    hint ? hintId : undefined,
    error ? errorId : undefined,
  ]
    .filter(Boolean)
    .join(' ') || undefined;

  return (
    <div className="text-field">
      <label className="text-field-label" htmlFor={inputId}>
        {label}
        {required && <span className="text-field-required"> (필수)</span>}
      </label>

      {hint && (
        <p id={hintId} className="text-field-hint">
          {hint}
        </p>
      )}

      <input
        {...inputProps}
        id={inputId}
        required={required}
        aria-invalid={error ? true : ariaInvalid}
        aria-describedby={descriptionIds}
        className={['text-field-input', className].filter(Boolean).join(' ')}
      />

      {error && (
        <p id={errorId} className="text-field-error">
          {error}
        </p>
      )}
    </div>
  );
}