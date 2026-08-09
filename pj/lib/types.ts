export type PageId = "home" | "imei" | "tax" | "pay" | "settings";

export type ImeiPair = { imei1: string; imei2: string };

export type ImeiResult = ImeiPair & {
  id: string;
  device: string;
  payment1: "Paid" | "Unpaid" | "Failed";
  payment2: "Paid" | "Unpaid" | "Failed" | "—";
  block: "Unblocked" | "Blocked" | "—";
  status: "Complete" | "Failed";
};

export type TaxResult = ImeiPair & {
  id: string;
  declarationId: string;
  total: number;
  customs: number;
  commercial: number;
  fine: number;
  status: "Paid" | "Pending" | "Failed";
  printable: boolean;
};

export type Applicant = {
  nationalId: string;
  fullName: string;
  birthday: string;
  phone: string;
  address: string;
  email: string;
  division: string;
  officeCode: string;
};

export type Activity = {
  id: string;
  at: string;
  tone: "info" | "success" | "warning";
  message: string;
};
