import './FilterChips.css';

export type FilterOption = { value: string; label: string };
type FilterChipsProps = {
  label: string;
  options: readonly FilterOption[];
  value: string;
  onChange: (value: string) => void;
};

export function FilterChips({ label, options, value, onChange }: FilterChipsProps) {
  return (
    <div className="home-filters" role="group" aria-label={label}>
      {options.map((option) => (
        <button type="button" key={option.value} aria-pressed={value === option.value}
          className="home-filter" onClick={() => onChange(option.value)}>
          {option.label}
        </button>
      ))}
    </div>
  );
}
