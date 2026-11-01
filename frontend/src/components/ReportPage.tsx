import React, { useEffect, useState } from 'react';
import ReportForm from './ReportForm';

const ReportPage: React.FC = () => {
  const [authenticated, setAuthenticated] = useState(false);
  const [consentRequired, setConsentRequired] = useState(false);
  const [csrf, setCsrf] = useState('');
  const [initialized, setInitialized] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/me', { credentials: 'include' })
      .then(async response => {
        if (response.status === 401) return;
        if (!response.ok) throw new Error('Could not check session');
        const data = await response.json();
        setAuthenticated(data.authenticated);
        setConsentRequired(Boolean(data.consent_required));
        setCsrf(data.csrf_token || '');
      })
      .catch(err => setError(err.message))
      .finally(() => setInitialized(true));
  }, []);

  const chooseConsent = async (allow: boolean) => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch('/api/consent', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: JSON.stringify({ allow })
      });
      if (response.status === 401) { setAuthenticated(false); return; }
      if (!response.ok) throw new Error('Не удалось обработать согласие. Повторите попытку.');
      setConsentRequired(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка обработки согласия');
    } finally { setLoading(false); }
  };

  if (!initialized) return <div>Loading...</div>;

  if (authenticated && consentRequired) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100">
        <div className="p-8 bg-white rounded-lg shadow-md">
          <h1 className="text-2xl font-bold mb-4">Использование данных Яндекс ID</h1>
          <p className="mb-4">Разрешаете BionicPRO получить и сохранить ваши идентификатор, логин, имя и email из Яндекс ID?</p>
          <button disabled={loading} onClick={() => chooseConsent(true)}
            className="px-4 py-2 bg-blue-500 text-white rounded">Разрешить</button>
          <button disabled={loading} onClick={() => chooseConsent(false)} className="ml-4">Отказаться</button>
          {error && <div className="mt-4 text-red-700">{error}</div>}
        </div>
      </div>
    );
  }


  if (!authenticated) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100">
        <button onClick={() => { window.location.href = '/auth/login'; }}
          className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600">Login</button>
        {error && <div className="mt-4 text-red-700">{error}</div>}
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-100 px-4 py-12">
      <div className="mx-auto w-full max-w-3xl rounded-2xl bg-white p-6 shadow-sm sm:p-8">
        <h1 className="mb-2 text-2xl font-bold text-gray-900">
          Отчёты
        </h1>

        <ReportForm />
      </div>
    </div>
  );
};

export default ReportPage;
