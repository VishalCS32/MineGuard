/**
 * src/views/auth/LoginView.tsx
 *
 * MineGuard Login Screen supporting Email or Phone Number + Password,
 * and Google OAuth 2.0 Sign-In.
 */

import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { useAuth } from '@/auth/AuthContext';
import { authApi } from '@/api/auth';
import {
  IconEye,
  IconEyeOff,
  IconGoogle,
  IconLock,
  IconShield,
  IconUser,
  IconWarning,
} from '@/components/ui/icons';

interface LoginViewProps {
  onNavigateRegister: () => void;
  onNavigateForgotPassword: () => void;
  onNavigateDashboard?: () => void;
  onSuccess?: () => void;
}

export function LoginView({
  onNavigateRegister,
  onNavigateForgotPassword,
  onNavigateDashboard,
  onSuccess,
}: LoginViewProps) {
  const { login, error, clearError } = useAuth();
  const [identifier, setIdentifier] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLocalError(null);
    clearError();

    if (!identifier.trim()) {
      setLocalError('Please enter your registered email address or phone number.');
      return;
    }
    if (!password) {
      setLocalError('Please enter your account password.');
      return;
    }

    setSubmitting(true);
    try {
      await login({ identifier: identifier.trim(), password });
      onSuccess?.();
    } catch (err: unknown) {
      // Handled by AuthContext; fallback local message
      if (err instanceof Error && !error) {
        setLocalError(err.message);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleGoogleSignIn = async () => {
    try {
      const res = await authApi.getGoogleAuthUrl();
      if (res.configured && res.url) {
        window.location.href = res.url;
      } else {
        setLocalError(
          res.detail || 'Google OAuth is not configured on the server. Please set GOOGLE_CLIENT_ID.'
        );
      }
    } catch {
      setLocalError('Failed to initialize Google OAuth sign-in.');
    }
  };

  const displayError = localError || error;

  return (
    <div className="flex min-h-screen w-full items-center justify-center bg-plane p-4">
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
        className="w-full max-w-[420px] rounded-2xl border border-hairline bg-surface p-6 sm:p-8 shadow-card"
      >
        {onNavigateDashboard && (
          <button
            type="button"
            onClick={onNavigateDashboard}
            className="mb-4 inline-flex items-center gap-1.5 text-xs text-ink-3 hover:text-brand transition-colors cursor-pointer"
          >
            ← Back to Live Dashboard
          </button>
        )}

        {/* Brand Header */}
        <div className="text-center">
          <div className="mx-auto grid h-12 w-12 place-items-center rounded-xl bg-brand/12 text-brand ring-1 ring-brand/30 shadow-glow">
            <IconShield size={26} />
          </div>
          <h1 className="mt-4 text-xl font-bold tracking-tight text-ink">
            Sign In to <span className="text-brand">MineGuard</span>
          </h1>
          <p className="mt-1 text-xs text-ink-3">
            Real-time subsurface deformation &amp; hazard intelligence
          </p>
        </div>

        {/* Error Banner */}
        {displayError && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            className="mt-4 flex items-start gap-2.5 rounded-lg border border-critical/30 bg-critical/10 p-3 text-xs text-critical"
          >
            <span className="mt-0.5 shrink-0 text-critical">
              <IconWarning size={16} />
            </span>
            <div className="flex-1 leading-snug">{displayError}</div>
          </motion.div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} className="mt-5 space-y-3.5">
          {/* Identifier (Email or Phone) */}
          <div>
            <label className="block text-[11px] font-semibold uppercase tracking-wider text-ink-2">
              Email Address or Phone Number
            </label>
            <div className="relative mt-1">
              <span className="absolute inset-y-0 left-0 flex items-center pl-3 text-ink-3">
                <IconUser size={16} />
              </span>
              <input
                type="text"
                value={identifier}
                onChange={(e) => {
                  setIdentifier(e.target.value);
                  if (displayError) {
                    setLocalError(null);
                    clearError();
                  }
                }}
                placeholder="operator@mine.com or +91 98765 43210"
                autoComplete="username"
                className="focus-ring w-full rounded-lg border border-hairline bg-surface-2 py-2 pl-9 pr-3 text-xs text-ink placeholder-ink-3 transition-colors hover:border-hairline/80 focus:border-brand/70"
                disabled={submitting}
                required
              />
            </div>
          </div>

          {/* Password */}
          <div>
            <div className="flex items-center justify-between">
              <label className="block text-[11px] font-semibold uppercase tracking-wider text-ink-2">
                Password
              </label>
              <button
                type="button"
                onClick={onNavigateForgotPassword}
                className="text-[11px] font-medium text-brand hover:underline"
              >
                Forgot password?
              </button>
            </div>
            <div className="relative mt-1">
              <span className="absolute inset-y-0 left-0 flex items-center pl-3 text-ink-3">
                <IconLock size={16} />
              </span>
              <input
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  if (displayError) {
                    setLocalError(null);
                    clearError();
                  }
                }}
                placeholder="••••••••••••"
                autoComplete="current-password"
                className="focus-ring w-full rounded-lg border border-hairline bg-surface-2 py-2 pl-9 pr-10 text-xs text-ink placeholder-ink-3 transition-colors hover:border-hairline/80 focus:border-brand/70"
                disabled={submitting}
                required
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute inset-y-0 right-0 flex items-center pr-3 text-ink-3 hover:text-ink transition-colors"
                aria-label={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? <IconEyeOff size={16} /> : <IconEye size={16} />}
              </button>
            </div>
          </div>

          {/* Submit Button */}
          <button
            type="submit"
            disabled={submitting}
            className="focus-ring mt-2 flex w-full items-center justify-center rounded-lg bg-brand py-2.5 text-xs font-bold text-plane shadow-glow transition-all hover:bg-brand-dim active:scale-[0.99] disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {submitting ? (
              <span className="flex items-center gap-2">
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-plane border-t-transparent" />
                Authenticating...
              </span>
            ) : (
              'Sign In to Dashboard'
            )}
          </button>
        </form>

        {/* Divider */}
        <div className="relative my-5">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-hairline" />
          </div>
          <div className="relative flex justify-center text-[11px] uppercase">
            <span className="bg-surface px-2 text-ink-3 font-medium">Or continue with</span>
          </div>
        </div>

        {/* Google OAuth Button */}
        <button
          type="button"
          onClick={handleGoogleSignIn}
          disabled={submitting}
          className="focus-ring flex w-full items-center justify-center gap-2.5 rounded-lg border border-hairline bg-surface-2 py-2.5 text-xs font-semibold text-ink transition-colors hover:bg-surface-3 hover:border-hairline/80 active:scale-[0.99]"
        >
          <IconGoogle size={16} />
          <span>Continue with Google</span>
        </button>

        {/* Register Link */}
        <div className="mt-6 text-center text-xs text-ink-3">
          Don&apos;t have an account?{' '}
          <button
            type="button"
            onClick={onNavigateRegister}
            className="font-bold text-brand hover:underline"
          >
            Create account
          </button>
        </div>

        {/* Return to Dashboard */}
        {onNavigateDashboard && (
          <div className="mt-4 pt-3 border-t border-hairline/60 text-center">
            <button
              type="button"
              onClick={onNavigateDashboard}
              className="text-xs font-medium text-ink-3 hover:text-ink transition-colors cursor-pointer"
            >
              Continue without signing in (View Dashboard)
            </button>
          </div>
        )}
      </motion.div>
    </div>
  );
}
