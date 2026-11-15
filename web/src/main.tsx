import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";
import { AppShell } from "./components/AppShell";
import { Empty } from "./components/ui";
import Buscar from "./pages/Buscar";
import ComoFunciona from "./pages/ComoFunciona";
import Gastos from "./pages/Gastos";
import Inicio from "./pages/Inicio";
import Pagina from "./pages/Pagina";
import Reglamento from "./pages/Reglamento";
import "./styles.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 5 * 60_000, retry: 1, refetchOnWindowFocus: false } },
});

const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { path: "/", element: <Inicio /> },
      { path: "/gastos", element: <Gastos /> },
      { path: "/reglamento", element: <Reglamento /> },
      { path: "/reglamento/:id", element: <Reglamento /> },
      { path: "/buscar", element: <Buscar /> },
      { path: "/paginas/:id", element: <Pagina /> },
      { path: "/como-funciona", element: <ComoFunciona /> },
      { path: "*", element: <Empty>Página no encontrada.</Empty> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
