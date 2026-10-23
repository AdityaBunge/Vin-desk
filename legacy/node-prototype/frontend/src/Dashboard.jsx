import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import "./Dashboard.css";

function Dashboard() {
  const navigate = useNavigate();

  const [user, setUser] = useState(null);
  const [vehicleCount, setVehicleCount] = useState("--");
  const [loadingVehicles, setLoadingVehicles] = useState(true);

  useEffect(() => {
    const storedUser = localStorage.getItem("user");

    if (!storedUser) {
      navigate("/");
      return;
    }

    setUser(JSON.parse(storedUser));
  }, [navigate]);

  // Get vehicle count from backend
  useEffect(() => {
    const fetchVehicleCount = async () => {
      try {
        const token = localStorage.getItem("token");

        const response = await fetch(
          "http://localhost:5000/api/vehicles",
          {
            method: "GET",
            headers: {
              Authorization: `Bearer ${token}`,
            },
          }
        );

        const result = await response.json();

        console.log("Vehicle API response:", result);

        if (!response.ok) {
          console.error(result);
          setVehicleCount("--");
          return;
        }

        // Your backend returns the vehicles in data
        const vehicles = result.data || result.vehicles || result;

        if (Array.isArray(vehicles)) {
          setVehicleCount(vehicles.length);
        } else {
          console.error("Vehicle data is not an array:", result);
          setVehicleCount("--");
        }

      } catch (error) {
        console.error("Failed to fetch vehicles:", error);
        setVehicleCount("--");
      } finally {
        setLoadingVehicles(false);
      }
    };

    fetchVehicleCount();
  }, []);

  const logout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    navigate("/");
  };

  return (
    <div className="dashboard">

      {/* SIDEBAR */}
      <aside className="sidebar">

        <div className="brand">

          <div className="brand-logo">
            VD
          </div>

          <div>
            <h2>VinDesk</h2>
            <span>Dealership System</span>
          </div>

        </div>

        <nav className="navigation">

          <button className="nav-item active">
            🏠 Dashboard
          </button>

          <button
            className="nav-item"
            onClick={() => navigate("/vehicles")}
          >
            🚗 Vehicles
          </button>

          <button className="nav-item">
            👥 Customers
          </button>

          <button className="nav-item">
            💰 Sales
          </button>

          <button className="nav-item">
            🔧 Service
          </button>

          <button className="nav-item">
            📊 Reports
          </button>

        </nav>

        <button
          className="logout-button"
          onClick={logout}
        >
          Logout
        </button>

      </aside>


      {/* MAIN CONTENT */}
      <main className="main-content">

        {/* TOP BAR */}
        <header className="topbar">

          <div>
            <h1>Dashboard</h1>

            <p>
              Welcome back to VinDesk
            </p>
          </div>

          <div className="user-info">

            <div className="avatar">
              {user?.name?.charAt(0).toUpperCase() || "U"}
            </div>

            <div>

              <strong>
                {user?.name || "User"}
              </strong>

              <span>
                {user?.role || "User"}
              </span>

            </div>

          </div>

        </header>


        {/* STATISTICS */}
        <section className="stats-grid">

          {/* TOTAL VEHICLES */}
          <div className="stat-card">

            <div className="stat-icon">
              🚗
            </div>

            <div>

              <p>
                Total Vehicles
              </p>

              <h2>
                {loadingVehicles ? "..." : vehicleCount}
              </h2>

            </div>

          </div>


          {/* TOTAL SALES */}
          <div className="stat-card">

            <div className="stat-icon">
              💰
            </div>

            <div>

              <p>
                Total Sales
              </p>

              <h2>
                --
              </h2>

            </div>

          </div>


          {/* CUSTOMERS */}
          <div className="stat-card">

            <div className="stat-icon">
              👥
            </div>

            <div>

              <p>
                Customers
              </p>

              <h2>
                --
              </h2>

            </div>

          </div>


          {/* SERVICE JOBS */}
          <div className="stat-card">

            <div className="stat-icon">
              🔧
            </div>

            <div>

              <p>
                Service Jobs
              </p>

              <h2>
                --
              </h2>

            </div>

          </div>

        </section>


        {/* QUICK ACTIONS */}
        <section className="dashboard-section">

          <div className="section-header">

            <h2>
              Quick Actions
            </h2>

            <p>
              Common VinDesk operations
            </p>

          </div>


          <div className="actions-grid">

            <button
              className="action-card"
              onClick={() => navigate("/vehicles")}
            >

              <span>
                🔍
              </span>

              <div>

                <h3>
                  Search Vehicle
                </h3>

                <p>
                  Search by VIN or registration number
                </p>

              </div>

            </button>


            <button className="action-card">

              <span>
                ➕
              </span>

              <div>

                <h3>
                  Add Vehicle
                </h3>

                <p>
                  Register a new vehicle
                </p>

              </div>

            </button>


            <button className="action-card">

              <span>
                👤
              </span>

              <div>

                <h3>
                  Add Customer
                </h3>

                <p>
                  Create a customer record
                </p>

              </div>

            </button>


            <button className="action-card">

              <span>
                📊
              </span>

              <div>

                <h3>
                  Reports
                </h3>

                <p>
                  View dealership reports
                </p>

              </div>

            </button>

          </div>

        </section>

      </main>

    </div>
  );
}

export default Dashboard;