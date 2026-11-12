import React, { useEffect, useState } from 'react';
import ReportPage from './components/ReportPage';

const BFF_URL = process.env.REACT_APP_API_URL;

const App: React.FC = () => {
  const [checking, setChecking] = useState(true);
  const [checkFailed, setCheckFailed] = useState(false);

  useEffect(() => {
    fetch(`${BFF_URL}/auth/session`, { credentials: 'include' })
      .then(r => {
        if (r.status === 401) {
          window.location.href = `${BFF_URL}/auth/login`;   // аналог login-required
        } else {
          setChecking(false);
        }
      })
      .catch(() =>
      {
        setChecking(false);
        setCheckFailed(true);
      });
  }, []);

  if (checking)
    return <div>Loading...</div>;

  if (checkFailed) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100">
        <p className="mb-4 text-gray-600">Не удалось проверить сессию</p>
        <button onClick={() => window.location.href = `${BFF_URL}/auth/login`}
                className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600">Login</button>
      </div>
    );
  }

  return (
    <div className="App">
      <ReportPage />
    </div>
  );
};

export default App;