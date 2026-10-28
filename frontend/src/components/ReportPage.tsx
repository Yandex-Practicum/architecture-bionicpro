import React, { useState } from 'react';
import { useKeycloak } from '@react-keycloak/web';

type Report = {
  user_id: string;
  full_name: string;
  email: string;
  prosthesis_model: string;
  total_steps: number;
  total_distance_m: number;
  avg_load_kg: number;
  sessions_count: number;
  last_activity_at: string | null;
  updated_at: string;
};

const ReportPage: React.FC = () => {
  const { keycloak, initialized } = useKeycloak();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null);

  const downloadReport = async () => {
    if (!keycloak?.token) {
      setError('Not authenticated');
      return;
    }

    try {
      setLoading(true);
      setError(null);
      setReport(null);

      const response = await fetch(`${process.env.REACT_APP_API_URL}/reports`, {
        headers: {
          'Authorization': `Bearer ${keycloak.token}`
        }
      });

      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${response.status}`);
      }

      setReport(await response.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  };

  if (!initialized) {
    return <div>Loading...</div>;
  }

  if (!keycloak.authenticated) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100">
        <button
          onClick={() => keycloak.login()}
          className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
        >
          Login
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100">
      <div className="p-8 bg-white rounded-lg shadow-md">
        <h1 className="text-2xl font-bold mb-6">Usage Reports</h1>
        
        <button
          onClick={downloadReport}
          disabled={loading}
          className={`px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 ${
            loading ? 'opacity-50 cursor-not-allowed' : ''
          }`}
        >
          {loading ? 'Generating Report...' : 'Download Report'}
        </button>

        {error && (
          <div className="mt-4 p-4 bg-red-100 text-red-700 rounded">
            {error}
          </div>
        )}

        {report && (
          <div className="mt-6 space-y-2 text-sm">
            <p><b>User:</b> {report.full_name} ({report.user_id})</p>
            <p><b>Model:</b> {report.prosthesis_model}</p>
            <p><b>Steps:</b> {report.total_steps}</p>
            <p><b>Distance:</b> {(report.total_distance_m / 1000).toFixed(2)} km</p>
            <p><b>Avg load:</b> {Number(report.avg_load_kg).toFixed(1)} kg</p>
            <p><b>Sessions:</b> {report.sessions_count}</p>
            <p><b>Last activity:</b> {report.last_activity_at ?? '—'}</p>
          </div>
        )}
      </div>
    </div>
  );
};

export default ReportPage;