import { BrowserRouter, Route, Routes } from "react-router-dom";
import { BuyerPage } from "./buyer/BuyerPage";
import { StaffApp } from "./staff/StaffApp";

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/staff/*" element={<StaffApp />} />
        <Route path="*" element={<BuyerPage />} />
      </Routes>
    </BrowserRouter>
  );
}
