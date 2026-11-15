import React, { useState } from 'react';

interface ReportRow {
  username: string;
  report_date: string;
  prosthesis_model: string;
  prosthesis_type: string;
  grips_count: number;
  releases_count: number;
  mode_switches_count: number;
  modes_usage_minutes: Record<string, number>;
}

const ReportPage: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [notReady, setNotReady] = useState(false);
  const [report, setReport] = useState<ReportRow[] | null>(null);

  const loadReport = async () => {
    try {
      setLoading(true);
      setError(null);
      setNotReady(false);

      const response = await fetch(`${process.env.REACT_APP_API_URL}/api/reports`, {
        credentials: 'include'
      });

      if (response.status === 401) {
        window.location.href = `${process.env.REACT_APP_API_URL}/auth/login`;
        return;
      }
      if (response.status === 404) {
        setNotReady(true);
        setReport(null);
        return;
      }
      if (!response.ok) throw new Error(`Ошибка: ${response.status}`);

      setReport(await response.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100">
      <div className="p-8 bg-white rounded-lg shadow-md max-w-2xl w-full">
        <h1 className="text-2xl font-bold mb-6">Usage Reports</h1>

        <button
          onClick={loadReport}
          disabled={loading}
          className={`px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 ${
            loading ? 'opacity-50 cursor-not-allowed' : ''
          }`}
        >
          {loading ? 'Загрузка...' : 'Мой отчёт'}
        </button>

        {notReady && (
          <div className="mt-4 p-4 bg-yellow-100 text-yellow-800 rounded">
            Отчёт ещё формируется. Попробуйте позже.
          </div>
        )}

        {error && (
          <div className="mt-4 p-4 bg-red-100 text-red-700 rounded">{error}</div>
        )}

        {report && (
          <div className="mt-6 space-y-4">
            {report.map((r) => (
              <div key={r.report_date} className="p-4 border rounded">
                <div className="font-semibold">{r.report_date} — {r.prosthesis_model} ({r.prosthesis_type})</div>
                <div className="text-sm mt-2">
                  Сжатий: {r.grips_count} · Разжиманий: {r.releases_count} · Переключений режима: {r.mode_switches_count}
                </div>
                <div className="text-sm">
                  Время по режимам: {Object.entries(r.modes_usage_minutes).map(([m, min]) => `${m}: ${min} мин`).join(', ') || '—'}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default ReportPage;