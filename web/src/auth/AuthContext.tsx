/**
 * src/auth/AuthContext.tsx
 *
 * Global Authentication Context and Provider for MineGuard.
 * Manages active user session, loading state, login, registration, and logout.
 */

import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import {
  authApi,
  UserProfile,
  LoginPayload,
  RegisterPayload,
  ResetPasswordPayload,
  ForgotPasswordResponse,
} from '@/api/auth';
import { ApiError } from '@/api/types';

interface AuthContextValue {
  user: UserProfile | null;
  loading: boolean;
  isAuthenticated: boolean;
  error: string | null;
  clearError: () => void;
  login: (payload: LoginPayload) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<void>;
  logout: () => Promise<void>;
  handleGoogleCallback: (code: string, redirectUri?: string) => Promise<void>;
  handleGoogleCredential: (credential: string) => Promise<void>;
  forgotPassword: (identifier: string) => Promise<ForgotPasswordResponse>;
  resetPassword: (payload: ResetPasswordPayload) => Promise<string>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const clearError = useCallback(() => setError(null), []);

  // Hydrate session on initial load
  useEffect(() => {
    let mounted = true;
    async function restoreSession() {
      try {
        const profile = await authApi.getMe();
        if (mounted) {
          setUser(profile);
        }
      } catch {
        // No active session or unauthenticated
        if (mounted) {
          setUser(null);
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    }
    restoreSession();
    return () => {
      mounted = false;
    };
  }, []);

  const login = useCallback(async (payload: LoginPayload) => {
    setError(null);
    try {
      const profile = await authApi.login(payload);
      setUser(profile);
    } catch (err: unknown) {
      const msg = err instanceof ApiError ? err.message : 'Invalid credentials. Please verify and try again.';
      setError(msg);
      throw err;
    }
  }, []);

  const register = useCallback(async (payload: RegisterPayload) => {
    setError(null);
    try {
      const profile = await authApi.register(payload);
      setUser(profile);
    } catch (err: unknown) {
      const msg = err instanceof ApiError ? err.message : 'Registration failed. Please try again.';
      setError(msg);
      throw err;
    }
  }, []);

  const logout = useCallback(async () => {
    setError(null);
    try {
      await authApi.logout();
    } catch (err) {
      console.error('Logout error:', err);
    } finally {
      setUser(null);
    }
  }, []);

  const handleGoogleCallback = useCallback(async (code: string, redirectUri?: string) => {
    setError(null);
    try {
      const profile = await authApi.googleCallback(code, redirectUri);
      setUser(profile);
    } catch (err: unknown) {
      const msg = err instanceof ApiError ? err.message : 'Google authentication failed.';
      setError(msg);
      throw err;
    }
  }, []);

  const handleGoogleCredential = useCallback(async (credential: string) => {
    setError(null);
    try {
      const profile = await authApi.googleCredential(credential);
      setUser(profile);
    } catch (err: unknown) {
      const msg = err instanceof ApiError ? err.message : 'Google sign-in failed.';
      setError(msg);
      throw err;
    }
  }, []);

  const forgotPassword = useCallback(async (identifier: string): Promise<ForgotPasswordResponse> => {
    setError(null);
    try {
      return await authApi.forgotPassword({ identifier });
    } catch (err: unknown) {
      const msg = err instanceof ApiError ? err.message : 'Unable to process password reset request.';
      setError(msg);
      throw err;
    }
  }, []);

  const resetPassword = useCallback(async (payload: ResetPasswordPayload): Promise<string> => {
    setError(null);
    try {
      const res = await authApi.resetPassword(payload);
      return res.message;
    } catch (err: unknown) {
      const msg = err instanceof ApiError ? err.message : 'Failed to reset password.';
      setError(msg);
      throw err;
    }
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        isAuthenticated: !!user,
        error,
        clearError,
        login,
        register,
        logout,
        handleGoogleCallback,
        handleGoogleCredential,
        forgotPassword,
        resetPassword,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
