import { useRef, useState, type ChangeEvent, type DragEvent } from "react";

import { ApiError, api } from "../lib/api";
import type { KnowledgeStatus, ModelInfo, ToolInfo } from "../types/api";

interface AdminSettingsViewProps {
  token: string;
  knowledge: KnowledgeStatus | null;
  models: ModelInfo[];
  activeModel: string;
  tools: ToolInfo[];
  enabledTools: string[];
  loading: boolean;
  onKnowledgeUpdated: (knowledge: KnowledgeStatus) => void;
  onModelUpdated: (activeModel: string, models: ModelInfo[]) => void;
  onEnabledToolsChange: (nextTools: string[]) => void;
  onUnauthorized: () => void;
}

export function AdminSettingsView({
  token,
  knowledge,
  models,
  activeModel,
  tools,
  enabledTools,
  loading,
  onKnowledgeUpdated,
  onModelUpdated,
  onEnabledToolsChange,
  onUnauthorized,
}: AdminSettingsViewProps) {
  const csvInputRef = useRef<HTMLInputElement | null>(null);
  const pdfInputRef = useRef<HTMLInputElement | null>(null);

  const [uploadingCsvs, setUploadingCsvs] = useState(false);
  const [uploadingPdf, setUploadingPdf] = useState(false);
  const [csvDragActive, setCsvDragActive] = useState(false);
  const [pdfDragActive, setPdfDragActive] = useState(false);
  const [csvError, setCsvError] = useState<string | null>(null);
  const [pdfError, setPdfError] = useState<string | null>(null);

  const [savingModel, setSavingModel] = useState<string | null>(null);
  const [modelError, setModelError] = useState<string | null>(null);

  async function processCsvFiles(fileList: FileList | File[]): Promise<void> {
    const files = Array.from(fileList);
    if (files.length === 0 || uploadingCsvs) {
      return;
    }
    setCsvError(null);
    setUploadingCsvs(true);
    try {
      const response = await api.uploadCsvs(token, files);
      onKnowledgeUpdated(response.knowledge);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 401) {
          onUnauthorized();
          return;
        }
        setCsvError(err.detail);
      } else {
        setCsvError("Não foi possível enviar os arquivos CSV agora.");
      }
    } finally {
      setUploadingCsvs(false);
      if (csvInputRef.current) {
        csvInputRef.current.value = "";
      }
    }
  }

  async function processPdfFile(fileList: FileList | File[]): Promise<void> {
    const file = Array.from(fileList)[0];
    if (!file || uploadingPdf) {
      return;
    }
    setPdfError(null);
    setUploadingPdf(true);
    try {
      const response = await api.uploadPdf(token, file);
      onKnowledgeUpdated(response.knowledge);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 401) {
          onUnauthorized();
          return;
        }
        setPdfError(err.detail);
      } else {
        setPdfError("Não foi possível processar o PDF agora.");
      }
    } finally {
      setUploadingPdf(false);
      if (pdfInputRef.current) {
        pdfInputRef.current.value = "";
      }
    }
  }

  function handleCsvInputChange(event: ChangeEvent<HTMLInputElement>): void {
    if (event.target.files) {
      void processCsvFiles(event.target.files);
    }
  }

  function handlePdfInputChange(event: ChangeEvent<HTMLInputElement>): void {
    if (event.target.files) {
      void processPdfFile(event.target.files);
    }
  }

  function handleCsvDrop(event: DragEvent<HTMLDivElement>): void {
    event.preventDefault();
    setCsvDragActive(false);
    if (event.dataTransfer.files.length > 0) {
      void processCsvFiles(event.dataTransfer.files);
    }
  }

  function handlePdfDrop(event: DragEvent<HTMLDivElement>): void {
    event.preventDefault();
    setPdfDragActive(false);
    if (event.dataTransfer.files.length > 0) {
      void processPdfFile(event.dataTransfer.files);
    }
  }

  async function handleSelectModel(modelId: string): Promise<void> {
    if (modelId === activeModel || savingModel !== null) {
      return;
    }
    setModelError(null);
    setSavingModel(modelId);
    try {
      const updated = await api.updateModel(token, modelId);
      onModelUpdated(updated.active_model, updated.models);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 401) {
          onUnauthorized();
          return;
        }
        setModelError(err.detail);
      } else {
        setModelError("Não foi possível atualizar o modelo agora.");
      }
    } finally {
      setSavingModel(null);
    }
  }

  function toggleTool(toolId: string): void {
    if (enabledTools.includes(toolId)) {
      onEnabledToolsChange(enabledTools.filter((id) => id !== toolId));
    } else {
      onEnabledToolsChange([...enabledTools, toolId]);
    }
  }

  const csvLoaded = Boolean(knowledge?.csvs.loaded);
  const pdfLoaded = Boolean(knowledge?.pdf.loaded);

  const csvSummary = csvLoaded && knowledge
    ? `${knowledge.csvs.file_names.length} arquivos · ${knowledge.csvs.record_count} registros${
        knowledge.csvs.audit_count > 0 ? ` · ${knowledge.csvs.audit_count} alertas ETL` : ""
      }`
    : "Envie os 6 CSVs operacionais ou um arquivo .zip";

  const pdfSummary = pdfLoaded && knowledge
    ? `${knowledge.pdf.file_names[0] ?? "políticas_da_loja.pdf"} · ${knowledge.pdf.record_count} trechos vetorizados`
    : "Envie o manual de políticas em PDF para vetorização";

  return (
    <main className="flex min-h-0 flex-1 flex-col items-center overflow-y-auto px-4 py-8 md:px-8 md:py-12">
      <div className="flex w-full max-w-[var(--container-chat)] flex-col gap-8">
        <header className="flex flex-col gap-1">
          <h1 className="m-0 text-[32px] font-medium leading-[110%] text-[var(--color-ink-primary)]">
            Ajustes
          </h1>
          <p className="m-0 text-[16px] font-normal leading-[130%] text-[var(--color-ink-secondary)]">
            Gerencie os arquivos da loja, o modelo Gemini 4 e as ferramentas do agente
          </p>
        </header>

        <section className="flex flex-col gap-4">
          <div className="flex flex-col gap-1">
            <h2 className="m-0 text-[24px] font-medium leading-[120%] text-[var(--color-ink-primary)]">
              Base de dados
            </h2>
            <p className="m-0 text-[14px] font-normal leading-[140%] text-[var(--color-ink-secondary)]">
              Envie os dois conjuntos de arquivos usados pelo agente. Reenviar um não altera o outro.
            </p>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div
              onDragOver={(event) => {
                event.preventDefault();
                setCsvDragActive(true);
              }}
              onDragLeave={() => setCsvDragActive(false)}
              onDrop={handleCsvDrop}
              className={`flex flex-col justify-between gap-4 rounded-[12px] border p-4 transition-colors ${
                csvDragActive
                  ? "border-[var(--color-ink-primary)] bg-[var(--color-bg-hover)]"
                  : "border-[var(--color-border-strong)] bg-[var(--color-bg-subtle)]"
              }`}
            >
              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[14px] font-medium leading-[140%] text-[var(--color-ink-primary)]">
                    Base operacional (CSVs)
                  </span>
                  <div className="flex items-center gap-1.5">
                    <span
                      className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                        csvLoaded
                          ? "bg-[var(--color-status-success)]"
                          : "bg-[var(--color-ink-muted)]"
                      }`}
                    />
                    <span className="text-[12px] font-normal leading-[140%] text-[var(--color-ink-secondary)]">
                      {csvLoaded ? "Carregada" : "Pendente"}
                    </span>
                  </div>
                </div>

                <p className="tabular-nums m-0 text-[12px] font-normal leading-[140%] text-[var(--color-ink-secondary)]">
                  {loading && !knowledge ? "Verificando base..." : csvSummary}
                </p>

                {csvError && (
                  <p
                    role="alert"
                    className="m-0 border-l-2 border-[var(--color-status-danger)] pl-2.5 text-[12px] leading-[140%] text-[var(--color-status-danger)]"
                  >
                    {csvError}
                  </p>
                )}
              </div>

              <div className="flex items-center justify-between gap-2">
                <span className="text-[12px] font-normal leading-[140%] text-[var(--color-ink-muted)]">
                  CSVs ou .zip
                </span>
                <input
                  ref={csvInputRef}
                  type="file"
                  multiple
                  accept=".csv,.zip"
                  onChange={handleCsvInputChange}
                  className="hidden"
                />
                <button
                  type="button"
                  disabled={uploadingCsvs}
                  onClick={() => csvInputRef.current?.click()}
                  className="flex h-7 items-center justify-center rounded-full border border-[var(--color-border-strong)] bg-[var(--color-bg-canvas)] px-3 text-[12px] font-medium leading-[16px] text-[var(--color-ink-primary)] hover:bg-[var(--color-bg-hover)] disabled:opacity-45"
                >
                  {uploadingCsvs
                    ? "Enviando..."
                    : csvLoaded
                      ? "Substituir CSVs"
                      : "Enviar CSVs"}
                </button>
              </div>
            </div>

            <div
              onDragOver={(event) => {
                event.preventDefault();
                setPdfDragActive(true);
              }}
              onDragLeave={() => setPdfDragActive(false)}
              onDrop={handlePdfDrop}
              className={`flex flex-col justify-between gap-4 rounded-[12px] border p-4 transition-colors ${
                pdfDragActive
                  ? "border-[var(--color-ink-primary)] bg-[var(--color-bg-hover)]"
                  : "border-[var(--color-border-strong)] bg-[var(--color-bg-subtle)]"
              }`}
            >
              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[14px] font-medium leading-[140%] text-[var(--color-ink-primary)]">
                    Manual de políticas (PDF)
                  </span>
                  <div className="flex items-center gap-1.5">
                    <span
                      className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                        pdfLoaded
                          ? "bg-[var(--color-status-success)]"
                          : "bg-[var(--color-ink-muted)]"
                      }`}
                    />
                    <span className="text-[12px] font-normal leading-[140%] text-[var(--color-ink-secondary)]">
                      {pdfLoaded ? "Carregado" : "Pendente"}
                    </span>
                  </div>
                </div>

                <p className="tabular-nums m-0 text-[12px] font-normal leading-[140%] text-[var(--color-ink-secondary)]">
                  {loading && !knowledge ? "Verificando manual..." : pdfSummary}
                </p>

                {pdfError && (
                  <p
                    role="alert"
                    className="m-0 border-l-2 border-[var(--color-status-danger)] pl-2.5 text-[12px] leading-[140%] text-[var(--color-status-danger)]"
                  >
                    {pdfError}
                  </p>
                )}
              </div>

              <div className="flex items-center justify-between gap-2">
                <span className="text-[12px] font-normal leading-[140%] text-[var(--color-ink-muted)]">
                  PDF único
                </span>
                <input
                  ref={pdfInputRef}
                  type="file"
                  accept=".pdf"
                  onChange={handlePdfInputChange}
                  className="hidden"
                />
                <button
                  type="button"
                  disabled={uploadingPdf}
                  onClick={() => pdfInputRef.current?.click()}
                  className="flex h-7 items-center justify-center rounded-full border border-[var(--color-border-strong)] bg-[var(--color-bg-canvas)] px-3 text-[12px] font-medium leading-[16px] text-[var(--color-ink-primary)] hover:bg-[var(--color-bg-hover)] disabled:opacity-45"
                >
                  {uploadingPdf
                    ? "Vetorizando..."
                    : pdfLoaded
                      ? "Substituir PDF"
                      : "Enviar PDF"}
                </button>
              </div>
            </div>
          </div>
        </section>

        <section className="flex flex-col gap-4">
          <div className="flex flex-col gap-1">
            <h2 className="m-0 text-[24px] font-medium leading-[120%] text-[var(--color-ink-primary)]">
              Modelo do agente
            </h2>
            <p className="m-0 text-[14px] font-normal leading-[140%] text-[var(--color-ink-secondary)]">
              Escolha qual modelo Gemini 4 responde no atendimento
            </p>
          </div>

          {modelError && (
            <p
              role="alert"
              className="m-0 border-l-2 border-[var(--color-status-danger)] pl-3 text-[14px] leading-[140%] text-[var(--color-status-danger)]"
            >
              {modelError}
            </p>
          )}

          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Modelo Gemini 4">
            {models.map((model) => {
              const selected = model.model_id === activeModel;
              const pending = savingModel === model.model_id;
              return (
                <button
                  key={model.model_id}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  disabled={savingModel !== null}
                  onClick={() => void handleSelectModel(model.model_id)}
                  className={`flex flex-col gap-1 rounded-[12px] border px-4 py-3 text-left transition-colors disabled:opacity-60 ${
                    selected
                      ? "border-[var(--color-ink-primary)] bg-[var(--color-bg-subtle)]"
                      : "border-[var(--color-border-strong)] bg-[var(--color-bg-canvas)] hover:bg-[var(--color-bg-subtle)]"
                  }`}
                >
                  <div className="flex w-full items-center justify-between gap-2">
                    <span className="text-[14px] font-medium leading-[140%] text-[var(--color-ink-primary)]">
                      {model.label}
                    </span>
                    <span
                      className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border-[1.5px] ${
                        selected || pending
                          ? "border-[var(--color-ink-primary)]"
                          : "border-[var(--color-border-strong)]"
                      }`}
                    >
                      {(selected || pending) && (
                        <span className="h-2 w-2 rounded-full bg-[var(--color-ink-primary)]" />
                      )}
                    </span>
                  </div>
                  <span className="text-[12px] font-normal leading-[140%] text-[var(--color-ink-secondary)]">
                    {model.description}
                  </span>
                </button>
              );
            })}
          </div>
        </section>

        <section className="flex flex-col gap-4">
          <div className="flex items-baseline justify-between gap-4">
            <div className="flex flex-col gap-1">
              <h2 className="m-0 text-[24px] font-medium leading-[120%] text-[var(--color-ink-primary)]">
                Ferramentas do agente
              </h2>
              <p className="m-0 text-[14px] font-normal leading-[140%] text-[var(--color-ink-secondary)]">
                Desative ferramentas para testar limites de resposta sem alucinação
              </p>
            </div>

            <div className="flex shrink-0 items-center gap-2 text-[12px] leading-[140%] text-[var(--color-ink-muted)]">
              <button
                type="button"
                onClick={() => onEnabledToolsChange(tools.map((item) => item.tool_id))}
                className="border-0 bg-transparent p-0 text-[12px] leading-[140%] text-[var(--color-ink-muted)] hover:text-[var(--color-ink-primary)]"
              >
                Todas
              </button>
              <span aria-hidden="true">·</span>
              <button
                type="button"
                onClick={() => onEnabledToolsChange([])}
                className="border-0 bg-transparent p-0 text-[12px] leading-[140%] text-[var(--color-ink-muted)] hover:text-[var(--color-ink-primary)]"
              >
                Nenhuma
              </button>
            </div>
          </div>

          <div className="flex flex-col border-t border-[var(--color-border-default)]">
            {tools.map((tool) => {
              const enabled = enabledTools.includes(tool.tool_id);
              return (
                <div
                  key={tool.tool_id}
                  className="flex items-center justify-between gap-4 border-b border-[var(--color-border-default)] py-4"
                >
                  <div className="flex flex-col gap-1">
                    <span
                      className={`text-[14px] leading-[140%] ${
                        enabled
                          ? "font-medium text-[var(--color-ink-primary)]"
                          : "font-normal text-[var(--color-ink-muted)]"
                      }`}
                    >
                      {tool.label}
                    </span>
                    <span
                      className={`text-[12px] font-normal leading-[140%] ${
                        enabled
                          ? "text-[var(--color-ink-secondary)]"
                          : "text-[var(--color-ink-muted)]"
                      }`}
                    >
                      {enabled ? tool.description : `Desativada neste teste · ${tool.description}`}
                    </span>
                  </div>

                  <button
                    type="button"
                    role="switch"
                    aria-checked={enabled}
                    aria-label={tool.label}
                    onClick={() => toggleTool(tool.tool_id)}
                    className={`flex h-[18px] w-8 shrink-0 items-center rounded-full border-0 p-0.5 transition-colors ${
                      enabled
                        ? "justify-end bg-[var(--color-ink-primary)]"
                        : "justify-start bg-[var(--color-border-strong)]"
                    }`}
                  >
                    <span className="h-3.5 w-3.5 rounded-full bg-[var(--color-bg-canvas)]" />
                  </button>
                </div>
              );
            })}
          </div>
        </section>
      </div>
    </main>
  );
}
