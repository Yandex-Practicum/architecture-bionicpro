import React, { useState } from 'react';

interface ReportRow {
  report_date: string;
  client_id: string;
  prosthesis_id: string;
  signals_count: number;
  movements_count: number;
}

interface Report {
  user_id: string;
  date_from: string;
  date_to: string;
  reports: ReportRow[];
}

const ReportForm: React.FC = () => {
  const [dateFrom, setDateFrom] = useState('2026-10-30');
  const [dateTo, setDateTo] = useState('2026-10-30');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [report, setReport] = useState<Report | null>(null);

  const getReport = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (loading) {
      return;
    }

    setError('');
    setReport(null);

    if (!dateFrom || !dateTo) {
      setError('Укажи начало и конец периода.');
      return;
    }

    if (dateFrom > dateTo) {
      setError('Начало периода не может быть позже окончания.');
      return;
    }

    setLoading(true);

    try {
      const params = new URLSearchParams({
        date_from: dateFrom,
        date_to: dateTo,
      });

      const response = await fetch(`/api/reports?${params.toString()}`, {
        credentials: 'same-origin',
        cache: 'no-store',
      });

      if (response.status === 401) {
        throw new Error(
          'Сессия отсутствует или истекла. Войди в приложение заново.'
        );
      }

      if (response.status === 403) {
        throw new Error(
          'Доступ к отчёту ограничен. Проверь, завершён ли шаг согласия.'
        );
      }

      if (response.status === 409) {
        throw new Error(
          'Данные за выбранный период ещё не подготовлены. ' +
          'Выбери другой период или повтори запрос позже.'
        );
      }

      if (!response.ok) {
        throw new Error(
          'Не удалось получить отчёт. Попробуй повторить запрос позже.'
        );
      }

      const data: { report_url: string } = await response.json();

      const fileResponse = await fetch(data.report_url, {
        credentials: 'same-origin',
        cache: 'no-store',
      });

      if (!fileResponse.ok) {
        throw new Error(
          'Не удалось загрузить файл отчёта. Повтори запрос.'
        );
      }

      const reportData: Report = await fileResponse.json();
      setReport(reportData);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Не удалось получить отчёт.'
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="w-full max-w-3xl">
      <p className="mb-6 text-sm text-gray-500">
        Выбери период, чтобы посмотреть данные о работе своих протезов.
      </p>

      <form
        onSubmit={getReport}
        className="grid grid-cols-1 gap-4 sm:grid-cols-2"
      >
        <div>
          <label
            htmlFor="report-date-from"
            className="mb-2 block text-sm font-medium text-gray-700"
          >
            Начало периода
          </label>
          <input
            id="report-date-from"
            type="date"
            value={dateFrom}
            required
            disabled={loading}
            onChange={(event) => {
              setDateFrom(event.target.value);
              setReport(null);
              setError('');
            }}
            className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200 disabled:bg-gray-100"
          />
        </div>

        <div>
          <label
            htmlFor="report-date-to"
            className="mb-2 block text-sm font-medium text-gray-700"
          >
            Конец периода
          </label>
          <input
            id="report-date-to"
            type="date"
            value={dateTo}
            required
            disabled={loading}
            onChange={(event) => {
              setDateTo(event.target.value);
              setReport(null);
              setError('');
            }}
            className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200 disabled:bg-gray-100"
          />
        </div>

        <button
          type="submit"
          disabled={loading}
          className="rounded-lg bg-blue-600 px-5 py-3 text-sm font-medium text-white transition hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:ring-offset-2 disabled:cursor-wait disabled:opacity-60 sm:col-span-2"
        >
          {loading ? 'Загрузка…' : 'Получить отчёт'}
        </button>
      </form>

      {error && (
        <div
          role="alert"
          className="mt-5 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"
        >
          {error}
        </div>
      )}

      {report && (
        <div className="mt-8" aria-live="polite">
          <h2 className="text-lg font-semibold text-gray-900">
            Результаты
          </h2>
          <p className="mb-4 mt-1 text-sm text-gray-500">
            Период: {report.date_from} — {report.date_to}
          </p>

          {report.reports.length === 0 ? (
            <div className="rounded-lg bg-gray-50 p-5 text-sm text-gray-600">
              Период обработан. Событий за выбранные дни нет.
            </div>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-gray-200">
              <table className="w-full text-left text-sm">
                <thead className="bg-gray-50 text-gray-600">
                  <tr>
                    <th scope="col" className="px-4 py-3 font-medium">
                      Дата
                    </th>
                    <th scope="col" className="px-4 py-3 font-medium">
                      Протез
                    </th>
                    <th
                      scope="col"
                      className="px-4 py-3 text-right font-medium"
                    >
                      Сигналы
                    </th>
                    <th
                      scope="col"
                      className="px-4 py-3 text-right font-medium"
                    >
                      Движения
                    </th>
                  </tr>
                </thead>

                <tbody className="divide-y divide-gray-100">
                  {report.reports.map((row) => (
                    <tr
                      key={`${row.report_date}-${row.client_id}-${row.prosthesis_id}`}
                      className="hover:bg-gray-50"
                    >
                      <td className="whitespace-nowrap px-4 py-3 text-gray-600">
                        {row.report_date}
                      </td>
                      <td className="px-4 py-3 font-medium text-gray-900">
                        {row.prosthesis_id}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-gray-700">
                        {row.signals_count}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-gray-700">
                        {row.movements_count}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </section>
  );
};

export default ReportForm;