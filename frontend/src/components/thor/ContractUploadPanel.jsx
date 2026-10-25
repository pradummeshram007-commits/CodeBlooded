import React, { useState, useRef } from 'react';
import {
  Upload,
  FileText,
  X,
  CheckCircle2,
  Clock,
  AlertCircle,
  Loader2,
  ArrowRight,
} from 'lucide-react';
import { uploadContractFile } from '../../services/api';

export default function ContractUploadPanel({ onUploadComplete, activeDocName }) {
  const [selectedFile, setSelectedFile] = useState(null);
  const [dragActive, setDragActive] = useState(false);
  const [uploadState, setUploadState] = useState('idle'); // idle | uploading | processing | success | error
  const [errorMessage, setErrorMessage] = useState('');
  const [pipelineStep, setPipelineStep] = useState(4); // 0..5
  const fileInputRef = useRef(null);

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

  const handleUploadSubmit = async () => {
    if (!selectedFile) return;
    setUploadState('uploading');
    setErrorMessage('');
    setPipelineStep(1);

    try {
      // Simulate stepper progress during network upload
      setTimeout(() => setPipelineStep(2), 600);
      setTimeout(() => setPipelineStep(3), 1200);

      const result = await uploadContractFile(selectedFile);
      setPipelineStep(5);
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
            Start with a PDF or TXT containing your agreement. THOR will extract its contractual terms and link the findings to their source clauses.
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
                {formatFileSize(selectedFile.size)} · Ready to analyze
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
                <span>Extracting with THOR...</span>
              </>
            ) : (
              <>
                <span>Extract Contract Intelligence</span>
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

      {/* Execution Pipeline Stepper */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2 pt-1 font-mono text-xs">
        <div
          className={`flex items-center gap-2 p-2 rounded border transition-colors ${
            pipelineStep >= 1
              ? 'bg-[#252E1F]/5 border-sage/40 text-primary-dark font-medium'
              : 'bg-cream/40 border-border-subtle text-secondary-olive'
          }`}
        >
          <CheckCircle2
            className={`w-4 h-4 ${pipelineStep >= 1 ? 'text-primary' : 'text-secondary-olive/40'}`}
          />
          <span className="truncate">01 Reading Document</span>
        </div>

        <div
          className={`flex items-center gap-2 p-2 rounded border transition-colors ${
            pipelineStep >= 2
              ? 'bg-[#252E1F]/5 border-sage/40 text-primary-dark font-medium'
              : 'bg-cream/40 border-border-subtle text-secondary-olive'
          }`}
        >
          <CheckCircle2
            className={`w-4 h-4 ${pipelineStep >= 2 ? 'text-primary' : 'text-secondary-olive/40'}`}
          />
          <span className="truncate">02 Identifying Clauses</span>
        </div>

        <div
          className={`flex items-center gap-2 p-2 rounded border transition-colors ${
            pipelineStep >= 3
              ? 'bg-[#252E1F]/5 border-sage/40 text-primary-dark font-medium'
              : 'bg-cream/40 border-border-subtle text-secondary-olive'
          }`}
        >
          <CheckCircle2
            className={`w-4 h-4 ${pipelineStep >= 3 ? 'text-primary' : 'text-secondary-olive/40'}`}
          />
          <span className="truncate">03 Extracting Fields</span>
        </div>

        <div
          className={`flex items-center gap-2 p-2 rounded border transition-colors ${
            pipelineStep >= 4
              ? 'bg-[#252E1F]/5 border-sage/40 text-primary-dark font-medium'
              : 'bg-cream/40 border-border-subtle text-secondary-olive'
          }`}
        >
          <CheckCircle2
            className={`w-4 h-4 ${pipelineStep >= 4 ? 'text-primary' : 'text-secondary-olive/40'}`}
          />
          <span className="truncate">04 Verifying Citations</span>
        </div>

        <div
          className={`flex items-center gap-2 p-2 rounded border transition-colors ${
            pipelineStep >= 5
              ? 'bg-accent-gold/15 border-accent-gold/40 text-dark-olive font-medium'
              : 'bg-cream/40 border-border-subtle text-secondary-olive'
          }`}
        >
          <Clock
            className={`w-4 h-4 ${pipelineStep >= 5 ? 'text-accent-gold' : 'text-secondary-olive/40'}`}
          />
          <span className="truncate">05 Collision Check</span>
        </div>
      </div>
    </section>
  );
}
