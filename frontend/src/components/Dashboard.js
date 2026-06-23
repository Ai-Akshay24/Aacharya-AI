import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Textarea } from './ui/textarea';
import { Card, CardHeader, CardTitle, CardContent } from './ui/card';
import { Label } from './ui/label';
import { Alert, AlertDescription } from './ui/alert';
import { LogOut, Send, Package, Plus, CheckCircle, AlertCircle } from 'lucide-react';
import { toast } from 'sonner';
import axios from 'axios';

// REMOVED THE BACKEND_URL AND API CONSTANTS
// The proxy in package.json will handle requests to /api/*

const Dashboard = () => {
  const navigate = useNavigate();
  const [alertMessage, setAlertMessage] = useState('');
  const [inventory, setInventory] = useState([]);
  const [newItemId, setNewItemId] = useState('');
  const [newItemName, setNewItemName] = useState('');
  const [newItemQuantity, setNewItemQuantity] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    fetchInventory();
  }, []);

  const getAuthHeaders = () => {
    const token = localStorage.getItem('access_token');
    return {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    };
  };

  const handleLogout = () => {
    localStorage.removeItem('access_token');
    toast.success('Logged out successfully');
    navigate('/login');
  };

  const fetchInventory = async () => {
    try {
      // Center-scoped: the backend derives the worker's center_id from the
      // bearer token itself. This call only ever returns rows belonging to
      // the logged-in worker's own center — no center_id is sent or needed
      // here, and no other center's stock is visible through this route.
      const response = await axios.get('/api/worker/get-inventory', {
        headers: getAuthHeaders()
      });
      setInventory(response.data);
    } catch (error) {
      console.error('Error fetching inventory:', error);
      if (error.response?.status === 401) {
        toast.error('Session expired. Please login again.');
        navigate('/login');
      }
    }
  };

  const handleBroadcastAlert = async () => {
    if (!alertMessage.trim()) {
      toast.error('Please enter an alert message');
      return;
    }

    setIsLoading(true);
    try {
      // Send the clean message only — the backend looks up the worker's
      // AshaCenter name from their center_id and prefixes it automatically
      // (e.g. "Nagamangala Sub-Centre: <message>"). Do not prefix on the
      // frontend, or the message will end up double-prefixed.
      await axios.post('/api/worker/broadcast-alert',
        { message: alertMessage },
        { headers: getAuthHeaders() }
      );
      toast.success('Alert broadcasted successfully!');
      setAlertMessage('');
    } catch (error) {
      console.error('Error broadcasting alert:', error);
      toast.error('Failed to broadcast alert');
    } finally {
      setIsLoading(false);
    }
  };

  const handleUpdateInventory = async (e) => {
    e.preventDefault();

    if (!newItemId.trim() || !newItemName.trim() || !newItemQuantity) {
      toast.error('Please enter item ID, item name, and quantity');
      return;
    }

    setIsLoading(true);
    try {
      // Exact contract expected by POST /api/worker/update-inventory:
      // { item_id, item_name, quantity }. No center_id is sent — the
      // backend resolves the target center entirely from the worker's
      // own JWT (current_worker.center_id), so this request can only
      // ever write to the logged-in worker's own center.
      await axios.post('/api/worker/update-inventory',
        {
          item_id: newItemId.trim(),
          item_name: newItemName.trim(),
          quantity: parseInt(newItemQuantity, 10)
        },
        { headers: getAuthHeaders() }
      );
      toast.success('Inventory updated successfully!');
      setNewItemId('');
      setNewItemName('');
      setNewItemQuantity('');
      fetchInventory();
    } catch (error) {
      console.error('Error updating inventory:', error);
      if (error.response?.status === 400) {
        toast.error(error.response?.data?.detail || 'This worker is not assigned to a center.');
      } else {
        toast.error('Failed to update inventory');
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50" style={{ fontFamily: 'Inter, sans-serif' }}>
      {/* Header */}
      <div className="bg-medical-blue text-white p-4 shadow-lg">
        <div className="container mx-auto flex justify-between items-center">
          <h1 className="text-2xl font-bold" data-testid="dashboard-header">
            Health Worker Dashboard
          </h1>
          <Button
            onClick={handleLogout}
            variant="outline"
            data-testid="logout-button"
            className="bg-white text-medical-blue hover:bg-gray-100 border-none"
          >
            <LogOut className="w-4 h-4 mr-2" />
            Logout
          </Button>
        </div>
      </div>

      <div className="container mx-auto p-4 md:p-8">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* Broadcast Alert Module */}
          <Card className="shadow-lg border-2 border-gray-100">
            <CardHeader className="bg-gradient-to-r from-yellow-50 to-orange-50 border-b">
              <CardTitle className="flex items-center text-medical-blue">
                <Send className="w-6 h-6 mr-2" />
                Broadcast Alert
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-6">
              <div className="space-y-4">
                <div>
                  <Label htmlFor="alert-message" className="text-gray-700 font-medium">
                    Alert Message
                  </Label>
                  <Textarea
                    id="alert-message"
                    placeholder="Enter urgent health alert or announcement..."
                    value={alertMessage}
                    onChange={(e) => setAlertMessage(e.target.value)}
                    rows={4}
                    data-testid="alert-message-input"
                    className="mt-2 border-gray-300 focus:border-medical-blue focus:ring-medical-blue"
                  />
                  <p className="text-xs text-gray-500 mt-1.5">
                    Your centre name is added automatically — no need to type it.
                  </p>
                </div>
                <Button
                  onClick={handleBroadcastAlert}
                  disabled={isLoading || !alertMessage.trim()}
                  data-testid="broadcast-alert-button"
                  className="w-full bg-medical-green hover:bg-green-600 text-white py-6 text-lg font-semibold shadow-md"
                >
                  <Send className="w-5 h-5 mr-2" />
                  Broadcast Alert
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* Inventory Manager Module */}
          <Card className="shadow-lg border-2 border-gray-100">
            <CardHeader className="bg-gradient-to-r from-blue-50 to-green-50 border-b">
              <CardTitle className="flex items-center text-medical-blue">
                <Package className="w-6 h-6 mr-2" />
                Inventory Manager
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-6">
              <form onSubmit={handleUpdateInventory} className="space-y-4 mb-6">
                <div>
                  <Label htmlFor="item-id" className="text-gray-700 font-medium">
                    Item ID
                  </Label>
                  <Input
                    id="item-id"
                    type="text"
                    placeholder="e.g., MED_PARA_500, VAC_BCG_001"
                    value={newItemId}
                    onChange={(e) => setNewItemId(e.target.value)}
                    data-testid="item-id-input"
                    className="mt-2 border-gray-300 focus:border-medical-blue focus:ring-medical-blue"
                  />
                  <p className="text-xs text-gray-500 mt-1.5">
                    Must match a known concept ID from the chatbot's knowledge base.
                  </p>
                </div>
                <div>
                  <Label htmlFor="item-name" className="text-gray-700 font-medium">
                    Item Name
                  </Label>
                  <Input
                    id="item-name"
                    type="text"
                    placeholder="e.g., Paracetamol 500mg"
                    value={newItemName}
                    onChange={(e) => setNewItemName(e.target.value)}
                    data-testid="item-name-input"
                    className="mt-2 border-gray-300 focus:border-medical-blue focus:ring-medical-blue"
                  />
                </div>
                <div>
                  <Label htmlFor="item-quantity" className="text-gray-700 font-medium">
                    Quantity
                  </Label>
                  <Input
                    id="item-quantity"
                    type="number"
                    placeholder="Enter quantity"
                    value={newItemQuantity}
                    onChange={(e) => setNewItemQuantity(e.target.value)}
                    min="0"
                    data-testid="item-quantity-input"
                    className="mt-2 border-gray-300 focus:border-medical-blue focus:ring-medical-blue"
                  />
                </div>
                <Button
                  type="submit"
                  disabled={isLoading}
                  data-testid="update-inventory-button"
                  className="w-full bg-medical-blue hover:bg-blue-700 text-white py-6 text-lg font-semibold shadow-md"
                >
                  <Plus className="w-5 h-5 mr-2" />
                  Add/Update Item
                </Button>
              </form>

              <div className="border-t pt-4">
                <h3 className="text-lg font-semibold text-gray-800 mb-4">Current Inventory</h3>
                <div className="space-y-2 max-h-64 overflow-y-auto" data-testid="inventory-list">
                  {inventory.length === 0 ? (
                    <p className="text-gray-500 text-center py-4">No inventory items</p>
                  ) : (
                    inventory.map((item) => (
                      <div
                        key={item.id}
                        className="flex justify-between items-center p-3 bg-gray-50 rounded-lg border border-gray-200 hover:bg-gray-100 transition-colors"
                        data-testid={`inventory-item-${item.id}`}
                      >
                        <div className="flex flex-col">
                          <span className="font-medium text-gray-800">{item.item_name}</span>
                          <span className="text-xs text-gray-400">{item.item_id}</span>
                        </div>
                        <span className={`px-3 py-1 rounded-full text-sm font-semibold ${
                          item.quantity > 50 ? 'bg-green-100 text-green-800' :
                          item.quantity > 20 ? 'bg-yellow-100 text-yellow-800' :
                          'bg-red-100 text-red-800'
                        }`}>
                          {item.quantity} units
                        </span>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;