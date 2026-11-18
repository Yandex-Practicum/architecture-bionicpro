import React, { useState } from 'react';

interface ReportSummary {
  username: string;
  prosthesis_model: string;
  prosthesis_type: string;
  date_from: string;
  date_to: string;
  days: number;
  grips_total: number;
  releases_total: number;
  mode_switches_total: number;
  grips_avg: number;
  releases_avg: number;
  mode_switches_avg: number;
  modes_total_minutes: Record<string, number>;
}

const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

const ReportPage: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notReady, setNotReady] = useState(false);
  const [report, setReport] = useState<ReportSummary | null>(null);
  const [fromCache, setFromCache] = useState<boolean | null>(null);
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');

  const loadReport = async (f: string = from, t: string = to) => {
    if (f && t && f > t) {
      setError('Дата начала позже даты окончания');
      return;
    }
    try {
      setLoading(true);
      setError(null);
      setNotReady(false);
      setReport(null);

      const qs = new URLSearchParams();
      if (f) qs.set('from', f);
      if (t) qs.set('to', t);
      const qsStr = qs.toString();

      const response = await fetch(
        `${process.env.REACT_APP_API_URL}/api/reports${qsStr ? `?${qsStr}` : ''}`,
        { credentials: 'include' }
      );

      if (response.status === 401) {
        window.location.href = `${process.env.REACT_APP_API_URL}/auth/login`;
        return;
      }
      if (response.status === 404) {
        setNotReady(true);
        return;
      }
      if (!response.ok) throw new Error(`Ошибка: ${response.status}`);

      const contentType = response.headers.get('content-type') ?? '';
      if (!contentType.includes('application/json')) {
        throw new Error('API вернул не JSON — возможно, сессия истекла, обновите страницу');
      }

      const { url, cached } = await response.json();
      setFromCache(cached);

      const cdnResponse = await fetch(url);
      if (!cdnResponse.ok) throw new Error(`CDN вернул: ${cdnResponse.status}`);
      setReport(await cdnResponse.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  };

  const applyPreset = (days: number) => {
    const t = new Date();
    t.setDate(t.getDate() - 1);
    const f = new Date(t);
    f.setDate(f.getDate() - (days - 1));
    setFrom(iso(f));
    setTo(iso(t));
    loadReport(iso(f), iso(t));
  };

  const yesterday = iso(new Date(Date.now() - 86400000));

  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100">
      <div className="p-8 bg-white rounded-lg shadow-md max-w-2xl w-full">
        <h1 className="text-2xl font-bold mb-6">Usage Reports</h1>

        <div className="flex flex-wrap items-center gap-3">
          <label className="text-sm text-gray-600">
            С{' '}
            <input
              type="date"
              value={from}
              max={to || yesterday}
              onChange={(e) => setFrom(e.target.value)}
              className="px-2 py-1 border rounded"
            />
          </label>
          <label className="text-sm text-gray-600">
            по{' '}
            <input
              type="date"
              value={to}
              max={yesterday}
              min={from || undefined}
              onChange={(e) => setTo(e.target.value)}
              className="px-2 py-1 border rounded"
            />
          </label>

          <button
            onClick={() => loadReport()}
            disabled={loading}
            className={`px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 ${
              loading ? 'opacity-50 cursor-not-allowed' : ''
            }`}
          >
            {loading ? 'Загрузка...' : 'Загрузить'}
          </button>

          {[7, 14, 30].map((d) => (
            <button
              key={d}
              onClick={() => applyPreset(d)}
              disabled={loading}
              className={`px-4 py-2 bg-gray-200 text-gray-700 rounded hover:bg-gray-300 ${
                loading ? 'opacity-50 cursor-not-allowed' : ''
              }`}
            >
              {d} дней
            </button>
          ))}
        </div>

        {notReady && (
          <div className="mt-4 p-4 bg-yellow-100 text-yellow-800 rounded">
            Отчёт ещё формируется. Попробуйте позже.
          </div>
        )}

        {error && (
          <div className="mt-4 p-4 bg-red-100 text-red-700 rounded">{error}</div>
        )}

        {report && (
          <div className="mt-6 p-4 border rounded">
            <div className="font-semibold text-lg">
              {report.prosthesis_model} ({report.prosthesis_type})
            </div>
            <div className="text-sm text-gray-500 mb-3">
              Период: {report.date_from} — {report.date_to} · дней с данными: {report.days}
              {fromCache !== null && (
                <span> · {fromCache ? 'из кеша S3' : 'сформирован сейчас'}</span>
              )}
            </div>
            <div className="text-sm">
              Сжатия: {report.grips_total} (в среднем {report.grips_avg}/день) ·{' '}
              Разжимания: {report.releases_total} ({report.releases_avg}/день) ·{' '}
              Переключения режима: {report.mode_switches_total} ({report.mode_switches_avg}/день)
            </div>
            <div className="text-sm mt-1">
              Время по режимам:{' '}
              {Object.entries(report.modes_total_minutes)
                .map(([mode, min]) => `${mode}: ${min} мин`)
                .join(', ') || '—'}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default ReportPage;