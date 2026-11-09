import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { failNextProfileRequest, MOCK_PASSWORD, resetMockState } from '../mocks/handlers';
import { routes } from '../routes';

// 이 파일의 모든 API 호출은 Mock 으로 처리한다 (T16 프로필 API 미연동).
vi.mock('../config/env', () => ({ env: { apiBaseUrl: '/api', mockEnabled: true } }));

beforeEach(() => resetMockState());

/** user@example.com 으로 로그인한 뒤 /account/profile 로 이동한다. */
async function openProfile() {
  const router = createMemoryRouter(routes, { initialEntries: ['/login'] });
  render(<RouterProvider router={router} />);
  fireEvent.change(await screen.findByLabelText(/^이메일/), { target: { value: 'user@example.com' } });
  fireEvent.change(screen.getByLabelText(/^비밀번호/), { target: { value: MOCK_PASSWORD } });
  fireEvent.click(screen.getByRole('button', { name: '로그인' }));
  await screen.findByRole('heading', { name: '내 계정' });
  await act(() => router.navigate('/account/profile'));
}

const startEdit = async () => fireEvent.click(await screen.findByRole('button', { name: '프로필 수정' }));
const type = (label: string | RegExp, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
const save = () => fireEvent.click(screen.getByRole('button', { name: '저장' }));

describe('profile page (mock API)', () => {
  it('shows my current profile in view mode', async () => {
    await openProfile();
    expect(await screen.findByText('백엔드 개발자 지망생')).toBeInTheDocument(); // 불러온 뒤
    expect(screen.getByRole('heading', { name: '내 프로필' })).toBeInTheDocument();
    expect(within(screen.getByRole('main')).getByText('일반 사용자')).toBeInTheDocument(); // 헤더에도 같은 이름이 있어 본문만 본다
    expect(screen.getByText('서울')).toBeInTheDocument();
    expect(screen.getByText('user@example.com')).toBeInTheDocument();
    expect(screen.getByText('입력하지 않았어요')).toBeInTheDocument(); // 비어 있는 자기소개
  });

  it('opens the edit form with current values', async () => {
    await openProfile();
    await startEdit();
    expect(await screen.findByLabelText(/^이름/)).toHaveValue('일반 사용자');
    expect(screen.getByLabelText('한 줄 소개')).toHaveValue('백엔드 개발자 지망생');
    expect(screen.getByLabelText('자기소개')).toHaveValue('');
  });

  it('saves a change and shows the re-fetched value', async () => {
    await openProfile();
    await startEdit();
    await screen.findByLabelText(/^이름/);
    type('자기소개', '데이터 분석가를 준비 중입니다.');
    save();

    expect(await screen.findByText('프로필을 저장했습니다.')).toBeInTheDocument();
    expect(screen.getByText('데이터 분석가를 준비 중입니다.')).toBeInTheDocument();
  });

  it('clears an optional field by saving it empty', async () => {
    await openProfile();
    await startEdit();
    await screen.findByLabelText(/^이름/);
    type('한 줄 소개', '');
    save();

    expect(await screen.findByText('프로필을 저장했습니다.')).toBeInTheDocument();
    expect(screen.queryByText('백엔드 개발자 지망생')).not.toBeInTheDocument();
    expect(screen.getAllByText('입력하지 않았어요')).toHaveLength(2);
  });

  it('updates the header name after the display name changes', async () => {
    await openProfile();
    await startEdit();
    await screen.findByLabelText(/^이름/);
    type(/^이름/, '새 이름');
    save();

    await screen.findByText('프로필을 저장했습니다.');
    expect(screen.getByRole('link', { name: '새 이름' })).toBeInTheDocument();
  });

  it('does not send a request when nothing changed', async () => {
    await openProfile();
    await startEdit();
    await screen.findByLabelText(/^이름/);
    failNextProfileRequest('PATCH', 500); // 요청이 나가면 실패 메시지가 떠야 한다
    save();

    expect(await screen.findByText('변경된 내용이 없습니다.')).toBeInTheDocument();
  });

  it('validates fields on the screen before sending anything', async () => {
    await openProfile();
    await startEdit();
    await screen.findByLabelText(/^이름/);
    failNextProfileRequest('PATCH', 500); // 요청이 나가면 저장 실패 메시지가 떠야 한다
    type(/^이름/, '   ');
    type('희망·거주 지역', 'x'.repeat(121));
    save();

    expect(await screen.findByText('입력한 내용을 확인해 주세요.')).toBeInTheDocument();
    expect(screen.getByLabelText(/^이름/)).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByText('필수 입력 항목입니다.')).toBeInTheDocument();
    expect(screen.getByLabelText('희망·거주 지역')).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByText('최대 120자까지 입력할 수 있습니다.')).toBeInTheDocument();
    expect(screen.queryByText(/저장하지 못했습니다/)).not.toBeInTheDocument();
  });

  it('shows a general message when the server returns 422 without field details', async () => {
    await openProfile();
    await startEdit();
    await screen.findByLabelText(/^이름/);
    type('자기소개', '내용');
    failNextProfileRequest('PATCH', 422);
    save();

    expect(await screen.findByText('입력한 내용을 확인해 주세요.')).toBeInTheDocument();
    expect(screen.getByLabelText('자기소개')).toHaveValue('내용');
  });

  it('shows a save failure and keeps what was typed', async () => {
    await openProfile();
    await startEdit();
    await screen.findByLabelText(/^이름/);
    type('자기소개', '작성 중인 내용');
    failNextProfileRequest('PATCH', 500);
    save();

    expect(await screen.findByText(/저장하지 못했습니다/)).toBeInTheDocument();
    expect(screen.getByLabelText('자기소개')).toHaveValue('작성 중인 내용');
  });

  it('restores the saved values on cancel', async () => {
    await openProfile();
    await startEdit();
    await screen.findByLabelText(/^이름/);
    type('한 줄 소개', '바꾸는 중');
    fireEvent.click(screen.getByRole('button', { name: '취소' }));

    expect(screen.getByText('백엔드 개발자 지망생')).toBeInTheDocument(); // 보기 화면으로 돌아옴
  });

  it('offers a retry when loading fails', async () => {
    const router = createMemoryRouter(routes, { initialEntries: ['/login'] });
    render(<RouterProvider router={router} />);
    fireEvent.change(await screen.findByLabelText(/^이메일/), { target: { value: 'user@example.com' } });
    fireEvent.change(screen.getByLabelText(/^비밀번호/), { target: { value: MOCK_PASSWORD } });
    fireEvent.click(screen.getByRole('button', { name: '로그인' }));
    await screen.findByRole('heading', { name: '내 계정' });
    failNextProfileRequest('GET', 503);
    await act(() => router.navigate('/account/profile'));

    expect(await screen.findByText('프로필을 불러오지 못했습니다')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(await within(screen.getByRole('main')).findByText('일반 사용자')).toBeInTheDocument();
  });
});
