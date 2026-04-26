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

  const signup = useMutation({
    mutationFn: ({
      email,
      password,
      accepted_terms,
      referral_code,
    }: {
      email: string;
      password: string;
      accepted_terms: boolean;
      referral_code?: string;
    }) => api.signup(email, password, accepted_terms, referral_code),
  });

  const logout = useMutation({
    mutationFn: api.logout,
    onSuccess: () => {
      qc.clear();
    },
  });

  const config = useQuery({
    queryKey: ['auth', 'config'],
    queryFn: api.publicConfig,
    staleTime: 10 * 60_000,
    retry: 0,
  });

  return { whoami, login, signup, logout, config };
}
