import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from './ui/button';
import { Languages } from 'lucide-react';

const LanguageSelector = () => {
  const navigate = useNavigate();

  const handleLanguageSelect = (languageCode) => {
    localStorage.setItem('selected_language', languageCode);
    navigate('/chat');
  };

  const languages = [
    { code: 'en', name: 'English', nativeName: 'English', gradient: 'from-blue-500 to-blue-600' },
    { code: 'hi', name: 'Hindi', nativeName: 'हिन्दी', gradient: 'from-orange-500 to-red-500' },
    { code: 'kn', name: 'Kannada', nativeName: 'ಕನ್ನಡ', gradient: 'from-yellow-500 to-orange-500' }
  ];

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-blue-50 to-teal-50 flex items-center justify-center p-4">
      <div className="max-w-5xl w-full">
        <div className="text-center mb-16">
          <div className="flex justify-center mb-8">
            <div className="relative">
              <div className="absolute inset-0 bg-gradient-to-r from-deep-blue to-electric-teal rounded-full blur-xl opacity-40 animate-pulse"></div>
              <div className="relative bg-gradient-to-r from-deep-blue to-electric-teal p-6 rounded-full shadow-2xl">
                <Languages className="w-16 h-16 text-white" />
              </div>
            </div>
          </div>
          <h1 className="text-5xl md:text-6xl font-bold text-deep-blue mb-4" style={{ fontFamily: 'Inter, sans-serif', letterSpacing: '-0.02em' }}>
            Aacharya AI
          </h1>
          <p className="text-xl text-gray-600 mb-2" style={{ fontFamily: 'Inter, sans-serif' }}>
            Your Multilingual Health Assistant
          </p>
          <p className="text-md text-gray-500" style={{ fontFamily: 'Inter, sans-serif' }}>
            Choose your preferred language to continue
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          {languages.map((lang) => (
            <button
              key={lang.code}
              onClick={() => handleLanguageSelect(lang.code)}
              data-testid={`language-${lang.code}-button`}
              className="group relative bg-white p-10 rounded-3xl shadow-lg hover:shadow-2xl transition-all duration-300 border-2 border-transparent hover:border-electric-teal transform hover:scale-105 overflow-hidden"
            >
              <div className={`absolute inset-0 bg-gradient-to-br ${lang.gradient} opacity-0 group-hover:opacity-5 transition-opacity duration-300`}></div>
              <div className="relative text-center">
                <div className={`inline-block mb-6 p-4 rounded-2xl bg-gradient-to-br ${lang.gradient} shadow-md group-hover:scale-110 transition-transform duration-300`}>
                  <Languages className="w-10 h-10 text-white" />
                </div>
                <h3 className="text-3xl font-bold text-gray-800 mb-2" style={{ fontFamily: 'Inter, sans-serif' }}>
                  {lang.nativeName}
                </h3>
                <p className="text-sm text-gray-500 font-medium" style={{ fontFamily: 'Inter, sans-serif' }}>
                  {lang.name}
                </p>
              </div>
            </button>
          ))}
        </div>

        <div className="mt-16 text-center">
          <div className="inline-flex items-center space-x-2 bg-white px-6 py-3 rounded-full shadow-md">
            <div className="w-2 h-2 bg-electric-teal rounded-full animate-pulse"></div>
            <p className="text-sm text-gray-600 font-medium" style={{ fontFamily: 'Inter, sans-serif' }}>
              Powered by AI • Multilingual Support • WHO Verified Information
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default LanguageSelector;