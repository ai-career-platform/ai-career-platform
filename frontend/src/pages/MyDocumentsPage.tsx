import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent, KeyboardEvent } from 'react';
import { useApi } from '../api/ApiContext';
import { useQuery } from '../api/useQuery';
import {
  ACCEPT, MAX_FILE_BYTES, documentErrorMessage, formatBytes, isAbortError, isPending, kindNames, saveDocument,
  statusNames, validateFile,
} from '../api/documents';
import type { UploadKind, UserDocument } from '../api/documents';
import { ApiError } from '../api/errors';
import { Button } from '../components/Button';
import { StatePanel } from '../components/StatePanel';
import { formatDateTime } from '../i18n/format';
import { env } from '../config/env';
import './MyDocumentsPage.css';

/** T49 Retry-After 와 같은 간격으로 처리 중 문서 상태를 다시 확인합니다. */
export const POLL_MS = 3000;

function ConfirmDelete({ doc, pending, error, onCancel, onConfirm }: {
  doc: UserDocument; pending: boolean; error: string; onCancel: () => void; onConfirm: () => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    box.current?.querySelector<HTMLElement>('button')?.focus();
    return () => { if (previous?.isConnected) previous.focus(); };
  }, []);
  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === 'Escape' && !pending) { e.preventDefault(); onCancel(); return; }
    if (e.key !== 'Tab') return;
    const controls = box.current?.querySelectorAll<HTMLElement>('button:not(:disabled)');
    if (!controls?.length) { e.preventDefault(); box.current?.focus(); return; }
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (!first || !last) return;
    if (e.shiftKey && (document.activeElement === first || document.activeElement === box.current)) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
  return <div className="documents-overlay">
    <div ref={box} className="documents-dialog" role="dialog" aria-modal="true" tabIndex={-1}
      aria-labelledby="documents-delete-title" aria-describedby="documents-delete-desc" onKeyDown={onKeyDown}>
      <h2 id="documents-delete-title">문서 삭제 확인</h2>
      <p id="documents-delete-desc">
        <strong className="documents-filename">{doc.original_filename}</strong> 문서를 삭제할까요?
        삭제 요청 후에는 다운로드할 수 없으며, 서버에서 삭제가 끝나면 목록에서 사라집니다.
      </p>
      {error && <p className="documents-error" role="alert">{error}</p>}
      <div className="documents-dialog-actions">
        <Button variant="outline" onClick={onCancel} disabled={pending}>취소</Button>
        <Button onClick={onConfirm} disabled={pending}>{pending ? '삭제 요청 중…' : '삭제'}</Button>
      </div>
    </div>
  </div>;
}

export function MyDocumentsPage() {
  const { documents } = useApi();
  // 첫 페이지를 불러온 뒤의 목록(더 보기·업로드·삭제·상태 확인 결과)은 setData 로 같은 데이터에 반영합니다.
  const listing = useQuery(['me-documents'], (signal) => documents.list(undefined, signal));
  const { setData: setListing, retry: reloadList } = listing;
  const phase: 'loading' | 'ready' | 'error' = listing.status === 'ready' ? 'ready' : listing.status === 'error' ? 'error' : 'loading';
  const loaded = listing.status === 'ready' ? listing.data : null;
  const docs = useMemo(() => loaded?.items ?? [], [loaded]);
  const cursor = loaded?.next_cursor ?? null;
  const setDocs = useCallback((update: (items: UserDocument[]) => UserDocument[]) =>
    setListing(page => ({ ...page, items: update(page.items) })), [setListing]);
  const [loadingMore, setLoadingMore] = useState(false);

  const [kind, setKind] = useState<UploadKind>('resume');
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const uploadBusy = useRef(false);
  const controller = useRef<AbortController | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const [notice, setNotice] = useState('');
  const [rowError, setRowError] = useState('');
  const [busyIds, setBusyIds] = useState<ReadonlySet<string>>(new Set());
  const [confirm, setConfirm] = useState<UserDocument | null>(null);
  const [deletePending, setDeletePending] = useState(false);
  const [deleteError, setDeleteError] = useState('');
  const mock = env.mockEnabled;

  useEffect(() => () => controller.current?.abort(), []);

  const remove = (id: string) => setDocs(previous => previous.filter(d => d.document_id !== id));
  const replace = (doc: UserDocument) => setDocs(previous => previous.map(d => d.document_id === doc.document_id ? doc : d));
  const setBusy = (id: string, on: boolean) => setBusyIds(previous => {
    const next = new Set(previous);
    if (on) next.add(id); else next.delete(id);
    return next;
  });

  const refreshPending = useCallback(async () => {
    const pending = docs.filter(d => isPending(d.status));
    await Promise.all(pending.map(async d => {
      try {
        const latest = await documents.get(d.document_id);
        setDocs(previous => previous.map(p => p.document_id === latest.document_id ? latest : p));
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
          setDocs(previous => previous.filter(p => p.document_id !== d.document_id));
          if (d.status === 'deleting') setNotice('문서 삭제가 완료되었습니다.');
        }
      }
    }));
  }, [docs, documents, setDocs]);

  const hasPending = docs.some(d => isPending(d.status));
  useEffect(() => {
    if (phase !== 'ready' || !hasPending) return;
    const timer = setTimeout(() => { void refreshPending(); }, POLL_MS);
    return () => clearTimeout(timer);
  }, [phase, hasPending, refreshPending]);

  async function loadMore() {
    if (!cursor || loadingMore) return;
    setLoadingMore(true); setRowError('');
    try {
      const page = await documents.list(cursor);
      setListing(previous => ({
        items: [...previous.items, ...page.items.filter(i => !previous.items.some(p => p.document_id === i.document_id))],
        next_cursor: page.next_cursor,
      }));
    } catch (error) {
      setRowError(documentErrorMessage(error, 'list'));
    } finally { setLoadingMore(false); }
  }

  function chooseFile(next: File | null) {
    setFile(next); setUploadError(''); setNotice('');
    setFileError(next ? validateFile(next) ?? '' : '');
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (uploadBusy.current) return;
    if (!file) { setFileError('올릴 파일을 선택해 주세요.'); return; }
    const invalid = validateFile(file);
    if (invalid) { setFileError(invalid); return; }
    uploadBusy.current = true;
    const ctrl = new AbortController();
    controller.current = ctrl;
    setUploading(true); setUploadError(''); setNotice('');
    try {
      const created = await documents.upload(file, kind, ctrl.signal);
      if (ctrl.signal.aborted) throw new DOMException('The operation was aborted.', 'AbortError');
      // 목록을 아직 못 불러왔다면(오류) 새 문서가 포함되도록 다시 불러옵니다.
      if (listing.status === 'ready') setDocs(previous => [created, ...previous.filter(d => d.document_id !== created.document_id)]);
      else reloadList();
      setNotice('업로드를 접수했습니다. 파일을 확인하는 중입니다.');
      setFile(null);
      if (fileInput.current) fileInput.current.value = '';
    } catch (error) {
      if (isAbortError(error) || ctrl.signal.aborted) {
        // 서버 접수 여부가 불확실하므로 성공으로 표시하지 않고 목록을 다시 불러옵니다.
        setNotice('업로드를 취소했습니다. 서버에 이미 접수되었는지 확인하려고 목록을 다시 불러옵니다. 접수된 문서는 목록에 표시되며 삭제할 수 있습니다.');
        reloadList();
      } else {
        setUploadError(documentErrorMessage(error, 'upload'));
      }
    } finally {
      uploadBusy.current = false;
      controller.current = null;
      setUploading(false);
    }
  }

  async function download(doc: UserDocument) {
    if (doc.status !== 'ready' || busyIds.has(doc.document_id)) return;
    setBusy(doc.document_id, true); setRowError(''); setNotice('');
    try {
      await saveDocument(documents, doc);
    } catch (error) {
      setRowError(documentErrorMessage(error, 'download'));
      if (error instanceof ApiError && error.status === 404) remove(doc.document_id);
      if (error instanceof ApiError && error.status === 409) {
        documents.get(doc.document_id).then(replace).catch(() => undefined);
      }
    } finally { setBusy(doc.document_id, false); }
  }

  function openDelete(doc: UserDocument) {
    if (doc.status === 'deleting' || busyIds.has(doc.document_id)) return;
    setDeleteError(''); setRowError(''); setNotice(''); setConfirm(doc);
  }

  async function confirmDelete() {
    if (!confirm || deletePending) return;
    const target = confirm;
    setDeletePending(true); setDeleteError(''); setBusy(target.document_id, true);
    try {
      const result = await documents.remove(target.document_id);
      replace({ ...target, ...result, status: 'deleting' });
      setNotice('삭제를 요청했습니다. 서버에서 삭제가 끝나면 목록에서 사라집니다.');
      setConfirm(null);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        remove(target.document_id);
        setNotice('이미 삭제되었거나 찾을 수 없는 문서라 목록에서 제거했습니다.');
        setConfirm(null);
      } else {
        setDeleteError(documentErrorMessage(error, 'delete'));
      }
    } finally {
      setDeletePending(false); setBusy(target.document_id, false);
    }
  }

  return <section className="documents-page" aria-labelledby="documents-title">
    <div inert={Boolean(confirm)}>
      <h1 id="documents-title">내 문서 관리</h1>
      {mock && <p className="documents-mode" role="status">Mock 모드: 가상 문서 상태만 흉내 내며 파일 내용은 저장하지 않습니다. 실제 서버 검증이 아닙니다.</p>}

      <form className="documents-upload" onSubmit={e => void submit(e)} aria-labelledby="documents-upload-title" noValidate>
        <h2 id="documents-upload-title">문서 올리기</h2>
        <p className="documents-privacy">
          이력서·포트폴리오에는 연락처 등 개인정보가 포함될 수 있습니다. 본인 문서만 올리고, 필요 없는 개인정보는 지운 뒤 올려 주세요.
          문서는 본인만 볼 수 있으며 공개 링크를 만들지 않습니다.
        </p>
        <fieldset className="documents-kind" disabled={uploading}>
          <legend>문서 유형</legend>
          {(['resume', 'portfolio'] as const).map(k => <label key={k}>
            <input type="radio" name="document-kind" value={k} checked={kind === k} onChange={() => setKind(k)} />
            {kindNames[k]}
          </label>)}
        </fieldset>
        <label className="documents-file-label" htmlFor="documents-file">파일 선택 (PDF 또는 DOCX)</label>
        <input id="documents-file" ref={fileInput} type="file" accept={ACCEPT} disabled={uploading}
          aria-describedby="documents-file-hint" aria-invalid={Boolean(fileError)}
          onChange={e => chooseFile(e.target.files?.[0] ?? null)} />
        <p id="documents-file-hint" className="documents-hint">PDF·DOCX만 가능하며 최대 {formatBytes(MAX_FILE_BYTES)}까지 올릴 수 있습니다.</p>
        {file && <p className="documents-selected">선택한 파일: <span className="documents-filename">{file.name}</span> ({formatBytes(file.size)})</p>}
        {fileError && <p className="documents-error" role="alert">{fileError}</p>}
        {uploadError && <p className="documents-error" role="alert">{uploadError}</p>}
        <div className="documents-upload-actions">
          <Button type="submit" disabled={uploading || !file || Boolean(fileError)}>{uploading ? '업로드 중…' : '업로드'}</Button>
          {uploading && <Button variant="outline" onClick={() => controller.current?.abort()}>업로드 취소</Button>}
        </div>
        {uploading && <p role="status" aria-live="polite">업로드 중입니다. 완료될 때까지 기다리거나 취소할 수 있습니다.</p>}
      </form>

      <div aria-live="polite" role="status" className="documents-notice">{notice}</div>

      <section aria-labelledby="documents-list-title">
        <div className="documents-list-head">
          <h2 id="documents-list-title">내 문서</h2>
          {phase === 'ready' && hasPending && <Button variant="outline" onClick={() => void refreshPending()}>상태 새로고침</Button>}
        </div>
        {rowError && <p className="documents-error" role="alert">{rowError}</p>}
        {phase === 'loading' && <StatePanel variant="loading" title="문서 목록을 불러오는 중" />}
        {phase === 'error' && <StatePanel variant="error" title="문서 목록을 불러오지 못했습니다"
          description="로그인 상태와 네트워크 연결을 확인해 주세요." actionLabel="다시 시도" onAction={reloadList} />}
        {phase === 'ready' && docs.length === 0 && <StatePanel variant="empty" title="등록한 문서가 없습니다"
          description="위에서 이력서나 포트폴리오를 올려 보세요." />}
        {phase === 'ready' && docs.length > 0 && <ul className="documents-list" aria-label="내 문서 목록">
          {docs.map(doc => {
            const busy = busyIds.has(doc.document_id);
            return <li key={doc.document_id} className={`documents-item documents-item--${doc.status}`}>
              <article aria-label={doc.original_filename}>
                <h3 className="documents-filename">{doc.original_filename}</h3>
                <dl className="documents-meta">
                  <div><dt>유형</dt><dd>{kindNames[doc.kind] ?? doc.kind}</dd></div>
                  <div><dt>크기</dt><dd>{formatBytes(doc.size_bytes)}</dd></div>
                  <div><dt>등록일</dt><dd><time dateTime={doc.created_at}>{formatDateTime(doc.created_at)}</time></dd></div>
                  <div><dt>상태</dt><dd><span className={`documents-status documents-status--${doc.status}`}>{statusNames[doc.status]}</span></dd></div>
                </dl>
                <div className="documents-item-actions">
                  <Button variant="outline" disabled={doc.status !== 'ready' || busy}
                    aria-label={`${doc.original_filename} 다운로드`} onClick={() => void download(doc)}>다운로드</Button>
                  <Button variant="outline" disabled={doc.status === 'deleting' || busy}
                    aria-label={`${doc.original_filename} 삭제`} onClick={() => openDelete(doc)}>
                    {doc.status === 'deleting' ? '삭제 처리 중' : '삭제'}
                  </Button>
                </div>
              </article>
            </li>;
          })}
        </ul>}
        {phase === 'ready' && cursor && <Button variant="outline" disabled={loadingMore} onClick={() => void loadMore()}>
          {loadingMore ? '불러오는 중…' : '더 보기'}
        </Button>}
      </section>
    </div>
    {confirm && <ConfirmDelete doc={confirm} pending={deletePending} error={deleteError}
      onCancel={() => { if (!deletePending) setConfirm(null); }} onConfirm={() => void confirmDelete()} />}
  </section>;
}
