import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError } from '@/lib/api';

export function useAuth() {
  const qc = useQueryClient();

  const whoami = useQuery({
    queryKey: ['auth', 'whoami'],
    queryFn: api.whoami,
    retry: (failureCount, error) => {
      if (error instanceof ApiError && error.status === 401) return false;
      return failureCount < 1;
    },
    staleTime: 5 * 60_000,
  });

  const login = useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) =>
      api.login(username, password),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['auth'] }),
  });

  const logout = useMutation({
    mutationFn: api.logout,
    onSuccess: () => {
      qc.clear();
    },
  });

  return { whoami, login, logout };
}
