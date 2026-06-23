import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from './ui/card';
import { Label } from './ui/label';
import { Alert, AlertDescription } from './ui/alert';
import { Lock, User, AlertCircle } from 'lucide-react';
import axios from 'axios';

// REMOVED THE BACKEND_URL AND API CONSTANTS
// The proxy in package.json will handle requests to /api/*

const Login = () => {
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleLogin = async (e) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);

    try {
      // Matches the refactored backend contract exactly:
      // POST /api/worker/login -> { username, password }
      const response = await axios.post('/api/worker/login', {
        username,
        password
      });

      // access_token is issued by the local deterministic auth server
      // (auth.py / create_access_token) — no external identity provider.
      const { access_token } = response.data;
      if (!access_token) {
        throw new Error('No access token returned by server.');
      }

      localStorage.setItem('access_token', access_token);
      navigate('/dashboard');
    } catch (err) {
      setError(err.response?.data?.detail || 'Login failed. Please check your credentials.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-green-50 flex items-center justify-center p-4" style={{ fontFamily: 'Inter, sans-serif' }}>
      <Card className="w-full max-w-md shadow-xl border-2 border-gray-100">
        <CardHeader className="text-center pb-8">
          <div className="flex justify-center mb-4">
            <div className="bg-medical-blue p-4 rounded-full shadow-lg">
              <Lock className="w-8 h-8 text-white" />
            </div>
          </div>
          <CardTitle className="text-3xl font-bold text-medical-blue">
            Health Worker Login
          </CardTitle>
          <CardDescription className="text-gray-600 mt-2">
            Access the worker portal to manage alerts and inventory
          </CardDescription>
        </CardHeader>
        <CardContent>
          {error && (
            <Alert variant="destructive" className="mb-4" data-testid="login-error">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <form onSubmit={handleLogin} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="username" className="text-gray-700 font-medium">
                Username
              </Label>
              <div className="relative">
                <User className="absolute left-3 top-3 h-5 w-5 text-gray-400" />
                <Input
                  id="username"
                  type="text"
                  placeholder="Enter your username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                  data-testid="username-input"
                  className="pl-10 border-gray-300 focus:border-medical-blue focus:ring-medical-blue"
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="password" className="text-gray-700 font-medium">
                Password
              </Label>
              <div className="relative">
                <Lock className="absolute left-3 top-3 h-5 w-5 text-gray-400" />
                <Input
                  id="password"
                  type="password"
                  placeholder="Enter your password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  data-testid="password-input"
                  className="pl-10 border-gray-300 focus:border-medical-blue focus:ring-medical-blue"
                />
              </div>
            </div>
            <Button
              type="submit"
              disabled={isLoading}
              data-testid="login-submit-button"
              className="w-full bg-medical-blue hover:bg-blue-700 text-white py-6 text-lg font-semibold shadow-md transition-all duration-300"
            >
              {isLoading ? 'Logging in...' : 'Login'}
            </Button>
          </form>
          <div className="mt-6 text-center">
            <Button
              variant="link"
              onClick={() => navigate('/chat')}
              data-testid="back-to-chat-link"
              className="text-medical-blue hover:text-medical-green"
            >
              Back to Chat
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default Login;