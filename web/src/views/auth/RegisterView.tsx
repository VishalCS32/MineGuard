/**
 * src/views/auth/RegisterView.tsx
 *
 * MineGuard Registration Screen with Full Name, Email, Phone number (with country code support),
 * Password strength indicators, and Google OAuth 2.0.
 */

import React, { useState, useMemo } from 'react';
import { motion } from 'framer-motion';
import { useAuth } from '@/auth/AuthContext';
import { authApi } from '@/api/auth';
import {
  IconCheck,
  IconEye,
  IconEyeOff,
  IconGoogle,
  IconLock,
  IconMail,
  IconPhone,
  IconShield,
  IconUser,
  IconWarning,
} from '@/components/ui/icons';

interface RegisterViewProps {
  onNavigateLogin: () => void;
  onNavigateDashboard?: () => void;
  onSuccess?: () => void;
}

const COUNTRY_CODES = [
  { code: 'IN', dial: '+91', label: 'India (+91)' },
  { code: 'US', dial: '+1', label: 'United States (+1)' },
  { code: 'GB', dial: '+44', label: 'United Kingdom (+44)' },
  { code: 'AU', dial: '+61', label: 'Australia (+61)' },
  { code: 'CA', dial: '+1', label: 'Canada (+1)' },
  { code: 'DE', dial: '+49', label: 'Germany (+49)' },
  { code: 'ZA', dial: '+27', label: 'South Africa (+27)' },
];

export function RegisterView({
  onNavigateLogin,
  onNavigateDashboard,
  onSuccess,
}: RegisterViewProps) {
  const { register, error, clearError } = useAuth();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [countryCode, setCountryCode] = useState('IN');
  const [phoneNumber, setPhoneNumber] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  // Live password strength analysis
  const passwordCriteria = useMemo(() => {
    return {
      length: password.length >= 8,
      lower: /[a-z]/.test(password),
      upper: /[A-Z]/.test(password),
      number: /[0-9]/.test(password),
      symbol: /[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/.test(password),
    };
  }, [password]);

  const strengthScore = useMemo(() => {
    return Object.values(passwordCriteria).filter(Boolean).length;
  }, [passwordCriteria]);

  const passwordsMatch = confirmPassword.length > 0 && password === confirmPassword;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLocalError(null);
    clearError();

    if (!name.trim()) {
      setLocalError('Please enter your full name.');
      return;
    }

    if (!email.trim() && !phoneNumber.trim()) {
      setLocalError('Please provide either an email address or a phone number.');
      return;
    }

    if (strengthScore < 5) {
      setLocalError('Please ensure your password meets all strength criteria.');
      return;
    }

    if (password !== confirmPassword) {
      setLocalError('Passwords do not match.');
      return;
    }

    setSubmitting(true);
    try {
      // Assemble dial code if phone entered without leading plus
      let cleanPhone = phoneNumber.trim();
      const dialCode = COUNTRY_CODES.find((c) => c.code === countryCode)?.dial || '+91';
      if (cleanPhone && !cleanPhone.startsWith('+')) {
        cleanPhone = `${dialCode}${cleanPhone.replace(/^0+/, '')}`;
      }

      await register({
        name: name.trim(),
        email: email.trim() || undefined,
        phoneNumber: cleanPhone || undefined,
        countryCode,
        password,
        confirmPassword,
      });
      onSuccess?.();
    } catch (err: unknown) {
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
    <div className="flex min-h-screen w-full items-center justify-center bg-plane p-4 py-8">
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
        className="w-full max-w-[460px] rounded-2xl border border-hairline bg-surface p-6 sm:p-8 shadow-card"
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
            Create a <span className="text-brand">MineGuard</span> Account
          </h1>
          <p className="mt-1 text-xs text-ink-3">
            Register to monitor geotechnical telemetry and hazard forecasts
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
          {/* Full Name */}
          <div>
            <label className="block text-[11px] font-semibold uppercase tracking-wider text-ink-2">
              Full Name *
            </label>
            <div className="relative mt-1">
              <span className="absolute inset-y-0 left-0 flex items-center pl-3 text-ink-3">
                <IconUser size={16} />
              </span>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Rajesh Sharma"
                autoComplete="name"
                className="focus-ring w-full rounded-lg border border-hairline bg-surface-2 py-2 pl-9 pr-3 text-xs text-ink placeholder-ink-3 transition-colors hover:border-hairline/80 focus:border-brand/70"
                disabled={submitting}
                required
              />
            </div>
          </div>

          {/* Email Address */}
          <div>
            <label className="block text-[11px] font-semibold uppercase tracking-wider text-ink-2">
              Email Address
            </label>
            <div className="relative mt-1">
              <span className="absolute inset-y-0 left-0 flex items-center pl-3 text-ink-3">
                <IconMail size={16} />
              </span>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="operator@mine.com"
                autoComplete="email"
                className="focus-ring w-full rounded-lg border border-hairline bg-surface-2 py-2 pl-9 pr-3 text-xs text-ink placeholder-ink-3 transition-colors hover:border-hairline/80 focus:border-brand/70"
                disabled={submitting}
              />
            </div>
          </div>

          {/* Phone Number with Country Code */}
          <div>
            <label className="block text-[11px] font-semibold uppercase tracking-wider text-ink-2">
              Phone Number
            </label>
            <div className="mt-1 flex gap-2">
              <select
                value={countryCode}
                onChange={(e) => setCountryCode(e.target.value)}
                className="focus-ring rounded-lg border border-hairline bg-surface-2 px-2.5 py-2 text-xs text-ink transition-colors hover:border-hairline/80 focus:border-brand/70 cursor-pointer shrink-0"
                disabled={submitting}
              >
                {COUNTRY_CODES.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.dial} ({c.code})
                  </option>
                ))}
              </select>

              <div className="relative min-w-0 flex-1">
                <span className="absolute inset-y-0 left-0 flex items-center pl-3 text-ink-3">
                  <IconPhone size={16} />
                </span>
                <input
                  type="tel"
                  value={phoneNumber}
                  onChange={(e) => setPhoneNumber(e.target.value)}
                  placeholder="98765 43210"
                  autoComplete="tel"
                  className="focus-ring w-full rounded-lg border border-hairline bg-surface-2 py-2 pl-9 pr-3 text-xs text-ink placeholder-ink-3 transition-colors hover:border-hairline/80 focus:border-brand/70"
                  disabled={submitting}
                />
              </div>
            </div>
            <p className="mt-1 text-[10px] text-ink-3">
              Provide either an email address or a mobile phone number for login.
            </p>
          </div>

          {/* Password */}
          <div>
            <label className="block text-[11px] font-semibold uppercase tracking-wider text-ink-2">
              Password *
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

            {/* Password Strength Meter */}
            {password.length > 0 && (
              <div className="mt-2 space-y-1.5 rounded-lg border border-hairline bg-surface-2/60 p-2 text-[10px]">
                <div className="flex items-center justify-between font-medium text-ink-3">
                  <span>Password Strength</span>
                  <span
                    className={
                      strengthScore <= 2
                        ? 'text-critical'
                        : strengthScore <= 4
                        ? 'text-warning'
                        : 'text-good'
                    }
                  >
                    {strengthScore <= 2 ? 'Weak' : strengthScore <= 4 ? 'Moderate' : 'Strong'}
                  </span>
                </div>
                {/* Strength Bar */}
                <div className="flex h-1 gap-1 overflow-hidden rounded-full bg-surface-3">
                  {[1, 2, 3, 4, 5].map((level) => (
                    <div
                      key={level}
                      className={`h-full flex-1 transition-all ${
                        level <= strengthScore
                          ? strengthScore <= 2
                            ? 'bg-critical'
                            : strengthScore <= 4
                            ? 'bg-warning'
                            : 'bg-good'
                          : 'bg-transparent'
                      }`}
                    />
                  ))}
                </div>
                {/* Requirements checklist */}
                <div className="grid grid-cols-2 gap-x-2 gap-y-0.5 pt-1 text-[9px] text-ink-3">
                  <div className={`flex items-center gap-1 ${passwordCriteria.length ? 'text-good' : ''}`}>
                    <IconCheck size={10} /> 8+ Characters
                  </div>
                  <div className={`flex items-center gap-1 ${passwordCriteria.lower ? 'text-good' : ''}`}>
                    <IconCheck size={10} /> Lowercase
                  </div>
                  <div className={`flex items-center gap-1 ${passwordCriteria.upper ? 'text-good' : ''}`}>
                    <IconCheck size={10} /> Uppercase
                  </div>
                  <div className={`flex items-center gap-1 ${passwordCriteria.number ? 'text-good' : ''}`}>
                    <IconCheck size={10} /> Number
                  </div>
                  <div className={`flex items-center gap-1 ${passwordCriteria.symbol ? 'text-good' : ''}`}>
                    <IconCheck size={10} /> Special symbol
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Confirm Password */}
          <div>
            <label className="block text-[11px] font-semibold uppercase tracking-wider text-ink-2">
              Confirm Password *
            </label>
            <div className="relative mt-1">
              <span className="absolute inset-y-0 left-0 flex items-center pl-3 text-ink-3">
                <IconLock size={16} />
              </span>
              <input
                type={showPassword ? 'text' : 'password'}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="Re-enter password"
                autoComplete="new-password"
                className="focus-ring w-full rounded-lg border border-hairline bg-surface-2 py-2 pl-9 pr-10 text-xs text-ink placeholder-ink-3 transition-colors hover:border-hairline/80 focus:border-brand/70"
                disabled={submitting}
                required
              />
              {confirmPassword && (
                <span
                  className={`absolute inset-y-0 right-0 flex items-center pr-3 ${
                    passwordsMatch ? 'text-good' : 'text-critical'
                  }`}
                >
                  {passwordsMatch ? <IconCheck size={16} /> : <IconWarning size={16} />}
                </span>
              )}
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
                Registering Account...
              </span>
            ) : (
              'Create Account & Enter'
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

        {/* Sign In Link */}
        <div className="mt-6 text-center text-xs text-ink-3">
          Already have an account?{' '}
          <button
            type="button"
            onClick={onNavigateLogin}
            className="font-bold text-brand hover:underline"
          >
            Sign in
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
