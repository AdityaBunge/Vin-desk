import {
  BrowserRouter,
  Routes,
  Route,
  Navigate
} from "react-router-dom";

import Login from "./Login";
import Dashboard from "./Dashboard";
import Vehicles from "./Vehicles";

function App() {

  const token = localStorage.getItem("token");

  return (
    <BrowserRouter>

      <Routes>

        <Route
          path="/"
          element={
            token
              ? <Navigate to="/dashboard" />
              : <Login />
          }
        />

        <Route
          path="/dashboard"
          element={
            token
              ? <Dashboard />
              : <Navigate to="/" />
          }
        />
        <Route
  path="/vehicles"
  element={
    token
      ? <Vehicles />
      : <Navigate to="/" />
  }
/>

      </Routes>

    </BrowserRouter>
  );
}

export default App;