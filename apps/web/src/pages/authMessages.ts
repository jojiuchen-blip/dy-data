import type { AccountActivationCheckData } from "../types/dashboard";

const verificationFallback = "暂无法完成账户核验，请联系管理员核对账号资料。";

export function activationFailureMessage(
  data: Pick<AccountActivationCheckData, "reason_code" | "certification_status">,
): string {
  switch (data.reason_code) {
    case "identity_not_matched":
      return "未找到与这两个 ID 匹配的门店记录。请确认两个 ID 来自导出文件的同一条记录；若确认无误，请联系管理员核对数据。";
    case "store_disabled":
      return "该门店已在系统中停用，暂无法激活。请联系管理员确认。";
    case "account_disabled":
      return "该账户已停用，暂无法激活或自助重置密码。请联系管理员。";
    case "account_type_unsupported":
      return "系统当前记录中的账号类型不支持自助激活。请使用认证成功的子机构经营号、子机构门店号或子机构区域号；若记录有误，请联系管理员。";
    case "certification_not_successful":
      return `当前子机构账号认证状态为“${data.certification_status || "未知"}”。认证状态刷新可能有延迟，若抖音来客显示“已激活”，请半个小时后再尝试激活。`;
    default:
      return verificationFallback;
  }
}

export function accountSubmitFailureMessage(
  error: { message: string; status: number; code?: string; reasonCode?: string; certificationStatus?: string },
): string | undefined {
  if (error.code === "activation_verification_failed") {
    return activationFailureMessage({ reason_code: error.reasonCode, certification_status: error.certificationStatus });
  }
  const messages: Record<string, string> = {
    "Username already exists": "该账号名已被使用，请更换一个。",
    "Password confirmation does not match": "两次输入的密码不一致，请重新确认。",
    "Account already initialized": "该账户已激活，请前往登录；忘记密码可重新设置。",
    "Account is not activated": "该账户尚未激活，请先完成账号激活。",
    "Account verification failed": verificationFallback,
  };
  return messages[error.message];
}
