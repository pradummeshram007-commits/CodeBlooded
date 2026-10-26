import React, { useEffect, useState, useRef } from 'react';
import {
  Upload,
  FileText,
  X,
  CheckCircle2,
  AlertCircle,
  Loader2,
  ArrowRight,
  RotateCcw,
} from 'lucide-react';
import { uploadContractFile } from '../../services/api';
import PipelineStepper, { usePipelineRun } from '../odin/PipelineStepper';

export default function ContractUploadPanel({ onUploadComplete, onPipelineUpdate, activeDocName }) {
  const [selectedFile, setSelectedFile] = useState(null);
  const [dragActive, setDragActive] = useState(false);
  const [uploadState, setUploadState] = useState('idle'); // idle | ready | uploading | success | error
  const [errorMessage, setErrorMessage] = useState('');
  const [uploadResult, setUploadResult] = useState(null);
  const fileInputRef = useRef(null);
  // ODIN runs THOR -> NORNS -> LOKI -> HEIMDALL on the uploaded document; the stepper follows the run live.
  const [run] = usePipelineRun(uploadResult?.pipeline?.run_id, uploadResult?.pipeline || null);

  useEffect(() => {
    if (run && onPipelineUpdate) onPipelineUpdate(run);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run]);

  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFileSelected(e.dataTransfer.files[0]);
    }
  };

  const handleFileChange = (e) => {
    if (e.target.files && e.target.files[0]) {
      handleFileSelected(e.target.files[0]);
    }
  };

  const handleFileSelected = (file) => {
    const validExts = ['.pdf', '.txt'];
    const hasValidExt = validExts.some((ext) => file.name.toLowerCase().endsWith(ext));
    if (!hasValidExt) {
      setErrorMessage('Please upload a valid PDF or plain text (.txt) contract file.');
      return;
    }
    setErrorMessage('');
    setSelectedFile(file);
    setUploadState('ready');
  };

  const handleRemoveFile = () => {
    setSelectedFile(null);
    setUploadState('idle');
    setErrorMessage('');
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleUploadAnother = () => {
    handleRemoveFile();
    setUploadResult(null);
  };

  const handleUploadSubmit = async () => {
    if (!selectedFile) return;
    setUploadState('uploading');
    setErrorMessage('');

    try {
      // Stores and segments the file, then ODIN starts the pipeline in the background and the stepper follows it.
      const result = await uploadContractFile(selectedFile);
      setUploadResult(result);
      setUploadState('success');

      if (onUploadComplete) {
        onUploadComplete(result);
      }
    } catch (err) {
      setUploadState('error');
      setErrorMessage(err.message || 'An error occurred during contract upload.');
    }
  };

  const formatFileSize = (bytes) => {
    if (!bytes) return '0 B';
    const mb = bytes / (1024 * 1024);
    if (mb >= 1) return `${mb.toFixed(1)} MB`;
    return `${(bytes / 1024).toFixed(0)} KB`;
  };

  return (
    <section className="bg-ivory border border-border-subtle rounded-xl p-6 sm:p-8 shadow-sm space-y-5">
      {/* Top Header & File Active Strip */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border-subtle/80 pb-5">
        <div>
          <h2 className="font-sans text-lg font-bold text-primary-dark flex items-center gap-2">
            <Upload className="w-5 h-5 text-primary" />
            <span>Upload your contract</span>
          </h2>
          <p className="font-sans text-xs sm:text-sm text-secondary-olive mt-0.5">
            Start with a PDF or TXT containing your agreement. ODIN then runs the whole pipeline on it: THOR extracts the terms with clause citations, NORNS dates the obligations and exposure, LOKI attacks it as the counterparty's lawyer, and HEIMDALL maps the event feed to it.
          </p>
        </div>

        {/* Selected or Active Document Pill */}
        {selectedFile ? (
          <div className="flex items-center gap-3 bg-cream border border-sage/60 px-3.5 py-2 rounded-lg shrink-0">
            <FileText className="w-5 h-5 text-primary-dark" />
            <div className="text-left font-mono text-xs">
              <div className="text-dark-olive font-semibold truncate max-w-[200px] sm:max-w-[260px]">
                {selectedFile.name}
              </div>
              <div className="text-secondary-olive text-[10px]">
                {formatFileSize(selectedFile.size)} · {uploadResult ? 'Uploaded' : 'Ready to analyze'}
              </div>
            </div>
            <button
              onClick={handleRemoveFile}
              className="p-1 text-secondary-olive hover:text-red-600 rounded transition-colors focus:outline-none"
              title="Remove File"
              aria-label="Remove File"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-3">
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileChange}
              accept=".pdf,.txt"
              className="hidden"
              id="contract-file-input"
            />
            <label
              htmlFor="contract-file-input"
              className="cursor-pointer inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-cream border border-border-subtle hover:border-primary font-mono text-xs text-primary-dark font-medium transition-all shadow-xs"
            >
              <Upload className="w-4 h-4 text-primary" />
              <span>Choose Contract PDF / TXT</span>
            </label>
          </div>
        )}
      </div>

      {/* Drag & Drop Zone if no file is selected */}
      {!selectedFile && (
        <div
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
          className={`border-2 border-dashed rounded-xl p-8 text-center transition-all cursor-pointer ${
            dragActive
              ? 'border-primary bg-primary/5'
              : 'border-border-subtle hover:border-primary/50 bg-cream/40'
          }`}
          onClick={() => fileInputRef.current?.click()}
        >
          <div className="w-10 h-10 mx-auto rounded-lg bg-cream border border-border-subtle flex items-center justify-center text-primary mb-2">
            <Upload className="w-5 h-5" />
          </div>
          <p className="font-mono text-xs font-semibold text-dark-olive">
            Drag and drop your contract here, or click to browse
          </p>
          <p className="font-mono text-[11px] text-secondary-olive mt-1">
            Supports standard commercial agreements in PDF or plain UTF-8 text (.txt)
          </p>
        </div>
      )}

      {/* Submit Action if file is selected */}
      {selectedFile && uploadState !== 'success' && (
        <div className="flex items-center justify-end gap-3 pt-1">
          <button
            onClick={handleUploadSubmit}
            disabled={uploadState === 'uploading'}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-primary-dark text-cream hover:bg-dark-olive font-mono text-xs font-semibold transition-all disabled:opacity-60 shadow-sm"
          >
            {uploadState === 'uploading' ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin text-cream" />
                <span>Uploading…</span>
              </>
            ) : (
              <>
                <span>Upload &amp; run ODIN pipeline</span>
                <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        </div>
      )}

      {/* Error Notice */}
      {errorMessage && (
        <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 font-mono text-xs flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{errorMessage}</span>
        </div>
      )}

      {/* Upload result + the live ODIN pipeline */}
      {uploadResult && (
        <div className="flex flex-wrap items-center justify-between gap-2 p-3 rounded-lg bg-cream/60 border border-border-subtle font-mono text-xs">
          <span className="flex items-center gap-2 text-dark-olive">
            <CheckCircle2 className="w-4 h-4 text-primary shrink-0" />
            {uploadResult.status === 'duplicate'
              ? `Already stored as ${uploadResult.doc_id}: no copy made. ODIN re-runs the pipeline (THOR skips text it already extracted).`
              : `Stored as ${uploadResult.doc_id} · ${uploadResult.clauses} clauses segmented.`}
            {!uploadResult.pipeline && ' The pipeline is off (odin.run_on_upload in config.yaml).'}
          </span>
          <button onClick={handleUploadAnother} className="inline-flex items-center gap-1 text-primary font-semibold hover:underline">
            <RotateCcw className="w-3.5 h-3.5" /> Upload another
          </button>
        </div>
      )}

      <div className="pt-1">
        <span className="block font-mono text-[10px] uppercase tracking-wider text-secondary-olive font-semibold mb-2">
          ODIN pipeline {run ? '' : '· starts when you upload'}
        </span>
        <PipelineStepper run={run} />
      </div>
    </section>
  );
}
