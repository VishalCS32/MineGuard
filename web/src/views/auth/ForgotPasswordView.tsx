/**
 * src/views/auth/ForgotPasswordView.tsx
 *
 * MineGuard Forgot Password Screen supporting password reset request
 * via registered email or telephone number.
 */

import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { useAuth } from '@/auth/AuthContext';
import {
  IconCheck,
  IconLock,
  IconUser,
  IconWarning,
} from '@/components/ui/icons';

interface ForgotPasswordViewProps {
  onNavigateLogin: () => void;
  onNavigateResetPassword: (token?: string) => void;
  onNavigateDashboard?: () => void;
}

export function ForgotPasswordView({
  onNavigateLogin,
  onNavigateResetPassword,
  onNavigateDashboard,
}: ForgotPasswordViewProps) {
  const { forgotPassword } = useAuth();
  const [identifier, setIdentifier] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successResult, setSuccessResult] = useState<{
    message: string;
    emailProviderConfigured: boolean;
    smsProviderConfigured: boolean;
    devToken?: string | null;
  } | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccessResult(null);

    if (!identifier.trim()) {
      setError('Please enter your registered email address or phone number.');
      return;
    }

    setSubmitting(true);
    try {
      const res = await forgotPassword(identifier.trim());
      setSuccessResult({
        message: res.message,
        emailProviderConfigured: res.emailProviderConfigured,
        smsProviderConfigured: res.smsProviderConfigured,
        devToken: res.devToken,
      });
    } catch (err: unknown) {
      if (err instanceof Error && !error) {
        setError(err.message);
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
            <IconLock size={24} />
          </div>
          <h1 className="mt-4 text-xl font-bold tracking-tight text-ink">
            Reset Your Password
          </h1>
          <p className="mt-1 text-xs text-ink-3">
            Enter your registered identifier to receive recovery instructions
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

        {/* Success Message Banner */}
        {successResult && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            className="mt-4 space-y-2 rounded-lg border border-good/30 bg-good/10 p-3.5 text-xs text-good"
          >
            <div className="flex items-start gap-2 font-semibold">
              <IconCheck size={16} className="mt-0.5 shrink-0" />
              <span>{successResult.message}</span>
            </div>

            {/* Provider notice */}
            {!successResult.emailProviderConfigured && !successResult.smsProviderConfigured && (
              <div className="rounded border border-amber-500/20 bg-amber-500/10 p-2 text-[11px] text-amber-300">
                <span className="font-semibold">Note:</span> Neither external SMTP nor SMS
                credentials are configured on this server.
                {successResult.devToken && (
                  <div className="mt-1.5 font-mono text-[10px] text-ink break-all">
                    Dev Token: <strong>{successResult.devToken}</strong>
                  </div>
                )}
              </div>
            )}

            {successResult.devToken && (
              <button
                type="button"
                onClick={() => onNavigateResetPassword(successResult.devToken!)}
                className="mt-1 inline-flex items-center gap-1 text-[11px] font-bold text-brand hover:underline"
              >
                Proceed to Reset Password with this Token &rarr;
              </button>
            )}
          </motion.div>
        )}

        {/* Request Form */}
        {!successResult && (
          <form onSubmit={handleSubmit} className="mt-5 space-y-4">
            <div>
              <label className="block text-[11px] font-semibold uppercase tracking-wider text-ink-2">
                Registered Email or Phone Number
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
                    if (error) setError(null);
                  }}
                  placeholder="operator@mine.com or +91 98765 43210"
                  autoComplete="username"
                  className="focus-ring w-full rounded-lg border border-hairline bg-surface-2 py-2 pl-9 pr-3 text-xs text-ink placeholder-ink-3 transition-colors hover:border-hairline/80 focus:border-brand/70"
                  disabled={submitting}
                  required
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={submitting}
              className="focus-ring flex w-full items-center justify-center rounded-lg bg-brand py-2.5 text-xs font-bold text-plane shadow-glow transition-all hover:bg-brand-dim active:scale-[0.99] disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {submitting ? (
                <span className="flex items-center gap-2">
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-plane border-t-transparent" />
                  Generating instructions...
                </span>
              ) : (
                'Send Recovery Instructions'
              )}
            </button>
          </form>
        )}

        <div className="mt-6 flex items-center justify-between text-xs text-ink-3">
          <button
            type="button"
            onClick={onNavigateLogin}
            className="font-semibold text-brand hover:underline"
          >
            &larr; Back to sign in
          </button>
          <button
            type="button"
            onClick={() => onNavigateResetPassword()}
            className="text-ink-3 hover:text-ink hover:underline"
          >
            Have a reset token?
          </button>
        </div>
      </motion.div>
    </div>
  );
}
