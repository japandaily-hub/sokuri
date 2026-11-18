/** 認証画面の共通カード UI。 */

export function AuthCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-[70vh] items-center justify-center px-4 py-12">
      <div className="w-full max-w-md rounded border border-kdz-line bg-[var(--white)] p-8 shadow-none">
        <h1 className="text-xl font-normal text-kdz-ink">{title}</h1>
        {subtitle ? <p className="mt-2 text-[15px] text-kdz-bodysoft">{subtitle}</p> : null}
        <div className="mt-6">{children}</div>
      </div>
    </div>
  );
}

export function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[15px] font-medium text-kdz-body">{label}</span>
      {children}
    </label>
  );
}

export const inputClass =
  "w-full rounded-kdz-s border border-[var(--line-input)] bg-[var(--white)] px-3.5 py-2.5 text-[15px] text-kdz-ink placeholder:text-kdz-bodysoft focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-200";

export const primaryButtonClass =
  "w-full rounded bg-brand-600 px-4 py-3 text-[15px] font-semibold text-white transition-colors hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50";

export function ErrorNote({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p className="rounded-kdz-s bg-[var(--danger-bg-soft)] px-3 py-2 text-[15px] text-kdz-danger" role="alert">
      {message}
    </p>
  );
}
