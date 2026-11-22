import { Eye, EyeOff } from "lucide-react";
import { useState, type FormEvent } from "react";

import { ApiError, api } from "../lib/api";
import type { AuthResponse } from "../types/api";

interface AuthScreenProps {
  onAuthenticated: (auth: AuthResponse) => void;
}

type AuthMode = "login" | "register";

export function AuthScreen({ onAuthenticated }: AuthScreenProps) {
  const [mode, setMode] = useState<AuthMode>("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isRegister = mode === "register";

  function switchMode(nextMode: AuthMode): void {
    setMode(nextMode);
    setError(null);
    setPassword("");
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setError(null);

    const trimmedEmail = email.trim();
    if (!trimmedEmail || !password) {
      setError("Preencha e-mail e senha para continuar.");
      return;
    }

    if (isRegister && password.length < 6) {
      setError("A senha precisa ter pelo menos 6 caracteres.");
      return;
    }

    setSubmitting(true);
    try {
      const response = isRegister
        ? await api.register(name.trim(), trimmedEmail, password)
        : await api.login(trimmedEmail, password);
      onAuthenticated(response);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError("Não foi possível conectar ao servidor agora.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-full w-full items-center justify-center bg-[var(--color-bg-canvas)] px-6 py-12">
      <div className="flex w-full max-w-[360px] flex-col gap-8">
        <header className="flex flex-col gap-4">
          <p className="m-0 text-[16px] font-medium leading-[120%] text-[var(--color-ink-primary)]">
            Empório da Música
          </p>
          <div className="flex flex-col gap-1">
            <h1 className="m-0 text-[32px] font-medium leading-[110%] text-[var(--color-ink-primary)]">
              {isRegister ? "Criar conta" : "Entrar"}
            </h1>
            <p className="m-0 text-[14px] font-normal leading-[140%] text-[var(--color-ink-secondary)]">
              {isRegister
                ? "Crie seu acesso de cliente para conversar com a loja."
                : "Use seu e-mail e senha para acessar o atendimento."}
            </p>
          </div>
        </header>

        <form className="flex flex-col gap-4" onSubmit={handleSubmit} noValidate>
          {isRegister && (
            <label className="flex flex-col gap-2">
              <span className="text-[14px] font-medium leading-[140%] text-[var(--color-ink-primary)]">
                Nome
              </span>
              <input
                type="text"
                name="name"
                autoComplete="name"
                placeholder="Seu nome"
                value={name}
                onChange={(event) => setName(event.target.value)}
                disabled={submitting}
                className="h-11 w-full rounded-[12px] border border-[var(--color-border-strong)] bg-[var(--color-bg-canvas)] px-4 text-[14px] font-normal leading-[140%] text-[var(--color-ink-primary)] placeholder:text-[var(--color-ink-muted)] focus:border-[var(--color-ink-primary)] focus:outline-none disabled:opacity-45"
              />
            </label>
          )}

          <label className="flex flex-col gap-2">
            <span className="text-[14px] font-medium leading-[140%] text-[var(--color-ink-primary)]">
              E-mail
            </span>
            <input
              type="email"
              name="email"
              autoComplete="email"
              placeholder="user@user.com"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              disabled={submitting}
              required
              className="h-11 w-full rounded-[12px] border border-[var(--color-border-strong)] bg-[var(--color-bg-canvas)] px-4 text-[14px] font-normal leading-[140%] text-[var(--color-ink-primary)] placeholder:text-[var(--color-ink-muted)] focus:border-[var(--color-ink-primary)] focus:outline-none disabled:opacity-45"
            />
          </label>

          <label className="flex flex-col gap-2">
            <span className="text-[14px] font-medium leading-[140%] text-[var(--color-ink-primary)]">
              Senha
            </span>
            <div className="relative flex items-center">
              <input
                type={showPassword ? "text" : "password"}
                name="password"
                autoComplete={isRegister ? "new-password" : "current-password"}
                placeholder={isRegister ? "Mínimo 6 caracteres" : "••••••••"}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                disabled={submitting}
                required
                className="h-11 w-full rounded-[12px] border border-[var(--color-border-strong)] bg-[var(--color-bg-canvas)] pl-4 pr-11 text-[14px] font-normal leading-[140%] text-[var(--color-ink-primary)] placeholder:text-[var(--color-ink-muted)] focus:border-[var(--color-ink-primary)] focus:outline-none disabled:opacity-45"
              />
              <button
                type="button"
                onClick={() => setShowPassword((prev) => !prev)}
                aria-label={showPassword ? "Ocultar senha" : "Mostrar senha"}
                className="absolute right-3 flex h-7 w-7 items-center justify-center rounded-[6px] text-[var(--color-ink-muted)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-ink-primary)]"
              >
                {showPassword ? (
                  <EyeOff size={16} strokeWidth={1.5} />
                ) : (
                  <Eye size={16} strokeWidth={1.5} />
                )}
              </button>
            </div>
          </label>

          {error && (
            <div
              role="alert"
              className="border-l-2 border-[var(--color-status-danger)] py-1 pl-3 text-[14px] leading-[140%] text-[var(--color-status-danger)]"
            >
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="flex h-11 w-full items-center justify-center rounded-full bg-[var(--color-accent-primary)] text-[14px] font-medium leading-[18px] text-[var(--color-ink-inverse)] transition-opacity hover:opacity-90 disabled:opacity-45"
          >
            {submitting
              ? isRegister
                ? "Criando conta..."
                : "Entrando..."
              : isRegister
                ? "Criar conta"
                : "Entrar"}
          </button>
        </form>

        <div className="flex items-center justify-center gap-1 text-[14px] leading-[140%]">
          <span className="text-[var(--color-ink-secondary)]">
            {isRegister ? "Já tem uma conta?" : "Ainda não tem conta?"}
          </span>
          <button
            type="button"
            onClick={() => switchMode(isRegister ? "login" : "register")}
            className="border-0 bg-transparent p-0 text-[14px] font-medium leading-[140%] text-[var(--color-ink-primary)] hover:underline"
          >
            {isRegister ? "Entrar" : "Criar conta"}
          </button>
        </div>
      </div>
    </main>
  );
}
