import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { createBrowserRouter, RouterProvider } from 'react-router';
import { routerBasename } from './config/basePath';
import { routes } from './routes';
import './styles/global.css';

// Staging 은 /career/ 아래에서 서비스됩니다(Vite base). 로고 '/'·로그인·가입 링크가 모두 이 아래로 갑니다.
const router = createBrowserRouter(routes, { basename: routerBasename(import.meta.env.BASE_URL) });

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('#root element not found');
}

createRoot(rootElement).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
