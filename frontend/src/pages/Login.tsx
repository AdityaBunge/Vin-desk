import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowRight, ClipboardCheck, Eye, EyeOff, FileText, Lock, Mail, PackageSearch, Wrench } from "lucide-react";
import { type CSSProperties, type InputHTMLAttributes, type ReactNode, forwardRef, useCallback, useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { Navigate } from "react-router-dom";
import heroImage from "@/assets/login-urbania.png";
import { Alert, Button, Field, cx, errorText } from "@/components/ui";
import { useAuth } from "@/hooks/useAuth";
import { type LoginValues, loginSchema } from "@/validation/schemas";

// Shown only in development builds; the backend refuses demo accounts in production.
const DEMO_PASSWORD = "Demo@12345";
const DEMO_USERS: [string, string][] = [
  ["Service Manager", "manager@demo.local"],
  ["Inventory Staff", "inventory@demo.local"],
  ["Administrator", "admin@demo.local"],
];

const FEATURES: [typeof ClipboardCheck, string][] = [
  [ClipboardCheck, "Job cards"],
  [PackageSearch, "Parts & stock"],
  [FileText, "GST invoices"],
];

/** Length of the photo opening sequence before the page pops in (ms). */
const INTRO_MS = 2000;
const INTRO_EXIT_MS = 650;

/** Skip the opening for people who ask for less motion (and where media queries are unavailable). */
const wantsIntro = () =>
  typeof window !== "undefined" && typeof window.matchMedia === "function" && !window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Fades and lifts its content into place, `step` x 80 ms after the page appears
 *  (the page appears after the opening sequence: `--intro` holds that delay). */
function Rise({ step, className, children }: { step: number; className?: string; children: ReactNode }) {
  return <div className={cx("animate-rise", className)} style={{ animationDelay: `calc(var(--intro, 0ms) + ${120 + step * 80}ms)` } as CSSProperties}>{children}</div>;
}

/** Full-screen opening: the photo opens like cinema shutters, zooms gently while a beam of light
 *  sweeps across, then dissolves to reveal the sign-in page. Tap, click or any key skips it. */
function Intro({ leaving, onSkip }: { leaving: boolean; onSkip: () => void }) {
  useEffect(() => {
    const skip = () => onSkip();
    window.addEventListener("keydown", skip);
    return () => window.removeEventListener("keydown", skip);
  }, [onSkip]);
  return (
    <div aria-hidden onClick={onSkip}
      className={cx("fixed inset-0 z-50 cursor-pointer overflow-hidden bg-slate-950", leaving && "pointer-events-none animate-[intro-exit_650ms_cubic-bezier(0.4,0,0.2,1)_both]")}>
      <div className="absolute inset-0 animate-[shutter-open_1s_cubic-bezier(0.77,0,0.18,1)_both]">
        <img src={heroImage} alt="" className="h-full w-full animate-[intro-zoom_2.6s_cubic-bezier(0.16,1,0.3,1)_both] object-cover" />
        <div className="absolute inset-y-0 left-0 w-1/3 animate-[light-sweep_1.4s_ease-in-out_0.7s_both] bg-gradient-to-r from-transparent via-white/35 to-transparent mix-blend-overlay" />
        <div className="absolute inset-0 bg-gradient-to-t from-slate-950/70 via-transparent to-slate-950/20" />
      </div>
      <div className="absolute inset-x-0 bottom-10 flex flex-col items-center gap-2 animate-rise text-center [animation-delay:900ms]">
        <span className="grid h-12 w-12 place-items-center rounded-2xl bg-gradient-to-br from-brand-500 to-brand-800 shadow-lg shadow-black/40">
          <Wrench className="h-6 w-6 text-white" />
        </span>
        <p className="text-2xl font-semibold tracking-tight text-white drop-shadow">Vin Desk</p>
        <p className="text-xs tracking-[0.3em] text-white/70 uppercase">Service Centre Management</p>
      </div>
    </div>
  );
}

/** Text input with a leading icon (and an optional trailing control). Forwards the ref so
 *  react-hook-form's register() can read the value. */
const IconInput = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { icon: typeof Mail; trailing?: ReactNode }>(
  function IconInput({ icon: Icon, trailing, className, ...props }, ref) {
    return (
      <div className="group relative">
        <Icon className="pointer-events-none absolute top-1/2 left-3.5 h-4 w-4 -translate-y-1/2 text-slate-400 transition-colors group-focus-within:text-brand-600" aria-hidden />
        <input ref={ref} {...props} className={cx("input h-11 pl-10 sm:h-11", trailing ? "pr-11" : "", className)} />
        {trailing && <div className="absolute top-1/2 right-1.5 -translate-y-1/2">{trailing}</div>}
      </div>
    );
  },
);

export default function Login() {
  const { user, login } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  // Opening sequence: "playing" -> "leaving" (dissolve) -> "done" (removed).
  const [intro, setIntro] = useState<"playing" | "leaving" | "done">(() => (wantsIntro() ? "playing" : "done"));
  const [introDelay, setIntroDelay] = useState(() => (wantsIntro() ? INTRO_MS : 0));
  const [pageKey, setPageKey] = useState(0);
  useEffect(() => {
    if (intro === "playing") {
      const t = setTimeout(() => setIntro("leaving"), INTRO_MS);
      return () => clearTimeout(t);
    }
    if (intro === "leaving") {
      const t = setTimeout(() => setIntro("done"), INTRO_EXIT_MS);
      return () => clearTimeout(t);
    }
  }, [intro]);
  const skipIntro = useCallback(() => {
    if (intro !== "playing") return;
    setIntroDelay(0);
    setPageKey((k) => k + 1); // replay the page entrance right away
    setIntro("leaving");
  }, [intro]);
  const { register, handleSubmit, setValue, formState: { errors, isSubmitting } } = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  });
  if (user) return <Navigate to="/" replace />;

  const onSubmit = async (values: LoginValues) => {
    setError(null);
    try {
      await login(values.email, values.password);
    } catch (e) {
      setError(errorText(e));
    }
  };

  return (
    <>
    {intro !== "done" && <Intro leaving={intro === "leaving"} onSkip={skipIntro} />}
    <div key={pageKey} className="relative flex min-h-dvh flex-col overflow-hidden bg-slate-950 lg:flex-row"
      style={{ "--intro": `${introDelay}ms` } as CSSProperties}>
      {/* --- Hero: the photograph with a slow cinematic zoom --------------------------------- */}
      <section aria-label="Vin Desk" className="relative h-80 shrink-0 overflow-hidden sm:h-96 lg:h-auto lg:w-[58%]">
        {/* Desktop: a blurred, enlarged copy fills the panel behind the full, uncropped photo. */}
        {/* Pure CSS fade-ins (no load events), so the photo always ends up visible. */}
        <img src={heroImage} alt="" aria-hidden
          className="absolute inset-0 hidden h-full w-full scale-125 animate-[fade-in_1.2s_ease-out_both] object-cover blur-2xl brightness-[0.55] saturate-150 [animation-delay:var(--intro)] lg:block" />
        <div className="absolute inset-0 animate-[rise_1.1s_cubic-bezier(0.16,1,0.3,1)_both] overflow-hidden [animation-delay:var(--intro)] lg:inset-x-10 lg:top-12 lg:bottom-auto lg:aspect-video lg:rounded-3xl lg:shadow-2xl lg:shadow-black/50 lg:ring-1 lg:ring-white/15">
          <img src={heroImage} alt="Force Motors Urbania"
            className="h-full w-full animate-ken-burns object-cover will-change-transform" />
        </div>
        {/* Light leaks drifting across the scene */}
        <div aria-hidden className="pointer-events-none absolute -top-1/4 -left-1/4 h-[70%] w-[70%] animate-drift rounded-full bg-amber-200/25 blur-3xl mix-blend-soft-light" />
        <div aria-hidden className="pointer-events-none absolute -right-1/4 -bottom-1/3 h-[70%] w-[70%] animate-drift rounded-full bg-sky-300/20 blur-3xl mix-blend-soft-light [animation-delay:-7s]" />
        {/* Gradients: readable text at the bottom; on desktop, a soft fade into the form side */}
        <div aria-hidden className="absolute inset-0 bg-gradient-to-t from-slate-950/90 via-slate-950/25 to-transparent lg:via-transparent" />
        <div aria-hidden className="absolute inset-y-0 right-0 hidden w-40 bg-gradient-to-r from-transparent to-slate-950/40 lg:block" />

        <div className="absolute inset-x-0 bottom-0 p-6 pb-20 sm:p-10 sm:pb-24 lg:p-14">
          <Rise step={0}>
            <span className="inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-3 py-1 text-xs font-medium text-white/90 backdrop-blur-md">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 shadow-[0_0_8px] shadow-emerald-400" aria-hidden />
              Authorised Force Motors service
            </span>
          </Rise>
          <Rise step={1}>
            <h2 className="mt-4 max-w-lg text-2xl leading-tight font-semibold tracking-tight text-white sm:text-4xl">
              Every vehicle, from arrival<br className="hidden sm:block" /> to delivery.
            </h2>
          </Rise>
          <Rise step={2}>
            <p className="mt-3 hidden max-w-md text-sm text-white/70 sm:block">
              Job cards, inspections, parts and GST invoices for your workshop, in one place.
            </p>
          </Rise>
          <Rise step={3} className="mt-5 hidden flex-wrap gap-2 sm:flex">
            {FEATURES.map(([Icon, text]) => (
              <span key={text} className="inline-flex items-center gap-1.5 rounded-xl border border-white/15 bg-white/10 px-3 py-1.5 text-xs font-medium text-white/90 backdrop-blur-md">
                <Icon className="h-3.5 w-3.5" aria-hidden />{text}
              </span>
            ))}
          </Rise>
        </div>
      </section>

      {/* --- Sign-in ----------------------------------------------------------------------------- */}
      <main className="relative z-10 -mt-10 flex flex-1 items-start justify-center px-4 pb-10 sm:-mt-16 lg:mt-0 lg:items-center lg:px-10 lg:pb-0">
        {/* Soft page backdrop for the form side */}
        <div aria-hidden className="absolute inset-0 -z-10 hidden bg-[radial-gradient(60rem_40rem_at_100%_0%,rgb(47_107_176/0.35),transparent_60%),linear-gradient(180deg,#0b1526,#0f1f35)] lg:block" />
        <div className="w-full max-w-[400px]">
          <div className="animate-[pop_750ms_cubic-bezier(0.34,1.56,0.64,1)_both]" style={{ animationDelay: "calc(var(--intro) + 150ms)" }}>
            <div className="rounded-3xl border border-white/70 bg-white/95 p-6 shadow-2xl shadow-black/40 backdrop-blur-xl sm:p-8">
              <Rise step={2} className="mb-7 flex items-center gap-3">
                <span className="grid h-11 w-11 place-items-center rounded-2xl bg-gradient-to-br from-brand-500 to-brand-800 shadow-lg shadow-brand-900/30">
                  <Wrench className="h-5 w-5 text-white" aria-hidden />
                </span>
                <div>
                  <h1 className="text-xl font-semibold tracking-tight text-slate-900">Vin Desk</h1>
                  <p className="text-sm text-slate-500">Welcome back - sign in to continue</p>
                </div>
              </Rise>

              <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
                {error && <div className="animate-rise"><Alert tone="error">{error}</Alert></div>}
                <Rise step={3}>
                  <Field label="Email" error={errors.email?.message} required>
                    {(id, describedBy) => (
                      <IconInput icon={Mail} id={id} aria-describedby={describedBy} type="email" autoComplete="username" autoFocus
                        placeholder="you@yourcentre.in" {...register("email")} />
                    )}
                  </Field>
                </Rise>
                <Rise step={4}>
                  <Field label="Password" error={errors.password?.message} required>
                    {(id, describedBy) => (
                      <IconInput icon={Lock} id={id} aria-describedby={describedBy} type={showPassword ? "text" : "password"}
                        autoComplete="current-password" placeholder="••••••••" {...register("password")}
                        trailing={
                          <button type="button" onClick={() => setShowPassword((s) => !s)} aria-pressed={showPassword}
                            aria-label={showPassword ? "Hide what you typed" : "Show what you typed"}
                            className="grid h-8 w-8 place-items-center rounded-lg text-slate-400 transition-colors hover:bg-slate-900/5 hover:text-slate-700">
                            {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                          </button>
                        } />
                    )}
                  </Field>
                </Rise>
                <Rise step={5}>
                  <Button type="submit" loading={isSubmitting}
                    className="group relative h-11 w-full overflow-hidden bg-gradient-to-r from-brand-600 to-brand-800 text-[15px] shadow-lg shadow-brand-900/30 hover:from-brand-700 hover:to-brand-900 sm:h-11">
                    <span aria-hidden className="pointer-events-none absolute inset-y-0 left-0 w-1/3 animate-sheen bg-gradient-to-r from-transparent via-white/25 to-transparent" />
                    <span className="relative">Sign in</span>
                    {!isSubmitting && <ArrowRight className="relative h-4 w-4 transition-transform duration-200 group-hover:translate-x-1" aria-hidden />}
                  </Button>
                </Rise>
              </form>
            </div>
          </div>

          {import.meta.env.DEV && (
            <Rise step={6}>
              <div className="mt-4 rounded-2xl border border-white/10 bg-white/[0.06] p-4 text-xs text-slate-300 backdrop-blur-md">
                <p className="font-medium text-white">Development build: sign in as a demo user</p>
                <div className="mt-3 grid grid-cols-2 gap-2">
                  {DEMO_USERS.map(([role, email]) => (
                    <button key={email} type="button" disabled={isSubmitting}
                      className="h-9 rounded-lg border border-white/15 bg-white/10 px-2 text-xs font-medium text-white transition-colors hover:bg-white/20 disabled:opacity-50"
                      onClick={() => {
                        // Fill the form too, so a browser-saved login for this address cannot override it.
                        setValue("email", email);
                        setValue("password", DEMO_PASSWORD);
                        void onSubmit({ email, password: DEMO_PASSWORD });
                      }}>{role}</button>
                  ))}
                </div>
                <p className="mt-3 leading-relaxed text-slate-400">
                  Password <code className="rounded bg-white/10 px-1 text-slate-200">{DEMO_PASSWORD}</code>. These accounts are refused in production.
                </p>
              </div>
            </Rise>
          )}
          <p className="mt-6 text-center text-xs text-slate-500">© {new Date().getFullYear()} Positive Sales · Vin Desk</p>
        </div>
      </main>
    </div>
    </>
  );
}
