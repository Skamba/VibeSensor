import { QueryClient } from "@tanstack/query-core";

export function createUiQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        gcTime: 5 * 60 * 1000,
        refetchOnReconnect: true,
        refetchOnWindowFocus: false,
        retry: false,
      },
    },
  });
}
