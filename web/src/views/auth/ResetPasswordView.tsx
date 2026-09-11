/**
 * src/views/auth/ResetPasswordView.tsx
 *
 * MineGuard Reset Password Screen using one-time token.
 */

import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { useAuth } from '@/auth/AuthContext';
import {
  IconCheck,
  IconEye,
  IconEyeOff,
  IconLock,
  IconShield,
  IconWarning,
} from '@/components/ui/icons';

interface ResetPasswordViewProps {
  initialToken?: string;
  onNavigateLogin: () => void;
  onNavigateDashboard?: () => void;
}

export function ResetPasswordView({
  initialToken = '',
  onNavigateLogin,
  onNavigateDashboard,
}: ResetPasswordViewProps) {
  const { resetPassword } = useAuth();
  const [token, setToken] = useState(initialToken);
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);

    if (!token.trim()) {
      setError('Please provide the password reset token.');
      return;
    }

    if (password.length < 8) {
      setError('Password must be at least 8 characters long.');
      return;
    }

    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }

    setSubmitting(true);
    try {
      const msg = await resetPassword({
        token: token.trim(),
        password,
        confirmPassword,
      });
      setSuccess(msg);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Failed to reset password.');
      }
    } finally {
      setSubmitting(false);
    }
  };

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
            Set New Password
          </h1>
          <p className="mt-1 text-xs text-ink-3">
            Enter your one-time verification token and choose a strong password
          </p>
        </div>

        {/* Error Banner */}
        {error && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            className="mt-4 flex items-start gap-2.5 rounded-lg border border-critical/30 bg-critical/10 p-3 text-xs text-critical"
          >
            <span className="mt-0.5 shrink-0 text-critical">
              <IconWarning size={16} />
            </span>
            <div className="flex-1 leading-snug">{error}</div>
          </motion.div>
        )}

        {/* Success Banner */}
        {success && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            className="mt-4 space-y-3 rounded-lg border border-good/30 bg-good/10 p-4 text-xs text-good text-center"
          >
            <div className="flex items-center justify-center gap-1.5 font-bold">
              <IconCheck size={18} />
              <span>{success}</span>
            </div>
            <p className="text-ink-2 text-[11px]">
              All previous active sessions have been securely invalidated.
            </p>
            <button
              type="button"
              onClick={onNavigateLogin}
              className="mt-2 inline-flex w-full items-center justify-center rounded-lg bg-brand py-2 text-xs font-bold text-plane shadow-glow"
            >
              Sign In with New Password
            </button>
          </motion.div>
        )}

        {!success && (
          <form onSubmit={handleSubmit} className="mt-5 space-y-3.5">
            {/* Token */}
            <div>
              <label className="block text-[11px] font-semibold uppercase tracking-wider text-ink-2">
                One-Time Reset Token
              </label>
              <div className="relative mt-1">
                <input
                  type="text"
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  placeholder="Paste token from recovery email/SMS"
                  className="focus-ring w-full font-mono rounded-lg border border-hairline bg-surface-2 py-2 px-3 text-xs text-ink placeholder-ink-3 transition-colors hover:border-hairline/80 focus:border-brand/70"
                  disabled={submitting}
                  required
                />
              </div>
            </div>

            {/* New Password */}
            <div>
              <label className="block text-[11px] font-semibold uppercase tracking-wider text-ink-2">
                New Password
              </label>
              <div className="relative mt-1">
                <span className="absolute inset-y-0 left-0 flex items-center pl-3 text-ink-3">
                  <IconLock size={16} />
                </span>
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Min. 8 characters with mix of types"
                  autoComplete="new-password"
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

            {/* Confirm Password */}
            <div>
              <label className="block text-[11px] font-semibold uppercase tracking-wider text-ink-2">
                Confirm New Password
              </label>
              <div className="relative mt-1">
                <span className="absolute inset-y-0 left-0 flex items-center pl-3 text-ink-3">
                  <IconLock size={16} />
                </span>
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="Re-enter new password"
                  autoComplete="new-password"
                  className="focus-ring w-full rounded-lg border border-hairline bg-surface-2 py-2 pl-9 pr-10 text-xs text-ink placeholder-ink-3 transition-colors hover:border-hairline/80 focus:border-brand/70"
                  disabled={submitting}
                  required
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={submitting}
              className="focus-ring mt-2 flex w-full items-center justify-center rounded-lg bg-brand py-2.5 text-xs font-bold text-plane shadow-glow transition-all hover:bg-brand-dim active:scale-[0.99] disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {submitting ? (
                <span className="flex items-center gap-2">
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-plane border-t-transparent" />
                  Updating Password...
                </span>
              ) : (
                'Save New Password'
              )}
            </button>
          </form>
        )}

        <div className="mt-6 text-center text-xs text-ink-3">
          <button
            type="button"
            onClick={onNavigateLogin}
            className="font-bold text-brand hover:underline"
          >
            &larr; Return to sign in
          </button>
        </div>
      </motion.div>
    </div>
  );
}
