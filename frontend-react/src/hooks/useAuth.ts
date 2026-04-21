import useSWR from "swr";
import { apiPost, swrFetcher } from "@/api/client";

type Me = { username: string; display_name?: string };

export function useAuth() {
  const { data, error, isLoading, mutate } = useSWR<Me>(
    "/api/me",
    swrFetcher,
    {
      shouldRetryOnError: false,
    }
  );
  const logout = async () => {
    try {
      await apiPost("/api/logout");
    } finally {
      await mutate(undefined, { revalidate: false });
      window.location.replace("/login");
    }
  };
  return {
    user: data,
    loading: isLoading,
    unauthenticated: !!error && (error as { status?: number }).status === 401,
    logout,
  };
}
