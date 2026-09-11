/**
 * src/api/auth.ts
 *
 * Strongly-typed API client wrapper for MineGuard authentication services.
 */

import { apiClient } from './client';

export interface UserProfile {
  id: number;
  name: string;
  email: string | null;
  phoneNumber: string | null;
  role: string;
  emailVerified: boolean;
  phoneVerified: boolean;
  hasPassword: boolean;
  hasGoogle: boolean;
  createdAt: number;
  lastLoginAt: number | null;
}

export interface RegisterPayload {
  name: string;
  email?: string;
  phoneNumber?: string;
  countryCode?: string;
  password: string;
  confirmPassword: string;
}

export interface LoginPayload {
  identifier: string;
  password: string;
}

export interface ForgotPasswordPayload {
  identifier: string;
}

export interface ResetPasswordPayload {
  token: string;
  password: string;
  confirmPassword: string;
}

export interface ForgotPasswordResponse {
  status: string;
  message: string;
  emailProviderConfigured: boolean;
  smsProviderConfigured: boolean;
  devToken?: string | null;
}

export interface GoogleAuthUrlResponse {
  configured: boolean;
  url: string | null;
  detail?: string;
}

export const authApi = {
  async register(payload: RegisterPayload): Promise<UserProfile> {
    return apiClient.request<UserProfile>('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async login(payload: LoginPayload): Promise<UserProfile> {
    return apiClient.request<UserProfile>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async getMe(): Promise<UserProfile> {
    return apiClient.request<UserProfile>('/api/auth/me', {
      method: 'GET',
    });
  },

  async logout(): Promise<{ status: string; message: string }> {
    return apiClient.request<{ status: string; message: string }>('/api/auth/logout', {
      method: 'POST',
    });
  },

  async forgotPassword(payload: ForgotPasswordPayload): Promise<ForgotPasswordResponse> {
    return apiClient.request<ForgotPasswordResponse>('/api/auth/forgot-password', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async resetPassword(payload: ResetPasswordPayload): Promise<{ status: string; message: string }> {
    return apiClient.request<{ status: string; message: string }>('/api/auth/reset-password', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async getGoogleAuthUrl(): Promise<GoogleAuthUrlResponse> {
    return apiClient.request<GoogleAuthUrlResponse>('/api/auth/google/url', {
      method: 'GET',
    });
  },

  async googleCallback(code: string, redirectUri?: string): Promise<UserProfile> {
    return apiClient.request<UserProfile>('/api/auth/google/callback', {
      method: 'POST',
      body: JSON.stringify({ code, redirectUri }),
    });
  },

  async googleCredential(credential: string): Promise<UserProfile> {
    return apiClient.request<UserProfile>('/api/auth/google/credential', {
      method: 'POST',
      body: JSON.stringify({ credential }),
    });
  },
};
