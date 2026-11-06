// Draft matching for synthetic data only; replace with approved T139 contract.
const normalize = value => value.normalize('NFC').toLocaleLowerCase('ko');

export function findSkills(query, skills) {
  if (typeof query !== 'string' || !Array.isArray(skills)) throw new TypeError('검색어와 기술 목록을 확인해 주세요.');
  const term = normalize(query.trim());
  const length = Array.from(term).length;
  if (length < 2) return [];
  if (length > 60) throw new RangeError('검색어는 60자 이하여야 합니다.');
  const seen = new Set();
  const candidates = [];
  for (const skill of skills) {
    if (!skill || typeof skill.code !== 'string' || !skill.code.trim() || typeof skill.name !== 'string' || !skill.name.trim()) {
      throw new TypeError('기술 코드와 이름을 확인해 주세요.');
    }
    if (seen.has(skill.code)) continue;
    seen.add(skill.code);
    const name = normalize(skill.name);
    if (name.includes(term)) candidates.push({ code: skill.code, name: skill.name, prefix: name.startsWith(term) });
  }
  candidates.sort((a, b) => Number(b.prefix) - Number(a.prefix) || a.name.localeCompare(b.name, 'ko') || a.code.localeCompare(b.code));
  return candidates.slice(0, 20).map(({code, name}) => ({code, name}));
}
