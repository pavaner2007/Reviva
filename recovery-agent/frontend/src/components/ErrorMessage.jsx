// components/ErrorMessage.jsx
export default function ErrorMessage({ message }) {
  return (
    <div className="mx-auto max-w-xl mt-12">
      <div className="card p-6 border-red-200 bg-red-50">
        <div className="flex items-start gap-3">
          <div className="flex-shrink-0 w-8 h-8 rounded-full bg-red-100 flex items-center justify-center">
            <svg className="w-4 h-4 text-red-600" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
            </svg>
          </div>
          <div>
            <p className="font-semibold text-red-800 text-sm">Connection Error</p>
            <p className="text-red-700 text-sm mt-1">{message}</p>
            <p className="text-red-500 text-xs mt-2">Make sure the FastAPI backend is running on <code className="font-mono">http://localhost:8000</code></p>
          </div>
        </div>
      </div>
    </div>
  );
}
