// Synthetic UI only: actual T18 API, status and date contract remain pending.
export function isClosed(item, asOf) { return item.status==='closed' || (item.status==='published' && asOf && item.expires && item.expires < asOf); }
export function filterPostings(items, {query='', company='', role='', includeClosed=false, order='recent', asOf=''}={}) {
  if (!Array.isArray(items) || typeof query !== 'string' || typeof company !== 'string' || typeof role !== 'string') throw new TypeError('검색 조건을 확인하세요.');
  const term=query.trim().toLocaleLowerCase('ko');
  const sorted=items.filter(item => (item.status==='published' || item.status==='closed') && (includeClosed || !isClosed(item, asOf)) && (!company || item.company===company) && (!role || item.role===role) && [item.title,item.company,item.role].some(x=>x.toLocaleLowerCase('ko').includes(term)));
  sorted.sort((a,b)=>order==='deadline'?(a.expires || '9999').localeCompare(b.expires || '9999')||a.id.localeCompare(b.id):b.published.localeCompare(a.published)||a.id.localeCompare(b.id));
  return sorted;
}
