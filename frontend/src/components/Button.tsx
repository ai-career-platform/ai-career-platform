import type { ComponentPropsWithoutRef } from 'react';
import './Button.css';

export type ButtonProps = ComponentPropsWithoutRef<'button'> & {
  variant?: 'primary' | 'outline';
};

export function Button({ variant = 'primary', type = 'button', className, ...props }: ButtonProps) {
  return <button {...props} type={type} className={['ui-button', `ui-button--${variant}`, className].filter(Boolean).join(' ')} />;
}
