"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { DangerousActionDialog } from "@/components/risk/DangerousActionDialog";
import type { components } from "@/generated/api-types";
import { apiFetch } from "@/lib/api";

type AdminActionResponse = components["schemas"]["AdminActionResponse"];
type AdminAudit = components["schemas"]["AuditLogResponse"];
type AdminFeatureFlag = components["schemas"]["AdminFeatureFlagResponse"];
type AdminUserDetail = components["schemas"]["AdminUserDetail"];
type AdminUserListResponse = components["schemas"]["AdminUserListResponse"];
type AdminUserSummary = components["schemas"]["AdminUserSummary"];
type AuditListResponse = components["schemas"]["AuditListResponse"];
type SystemHealthResponse = components["schemas"]["SystemHealthResponse"];
type TenantUsageResponse = components["schemas"]["TenantUsageResponse"];

type AdminTenantsResponse = {
  tenants: AdminTenantSummary[];
};

type AdminTenantSummary = {
  tenant_id: string;
  name: string;
  slug: string;
  status: string;
  plan?: string | null;
  plan_name: string | null;
  subscription_status: string | null;
  trial_ends_at?: string | null;
  current_period_ends_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

type AdminTenantUsageResponse = {
  plan?: string | null;
  plan_name: string | null;
  subscription_status: string | null;
  trial_ends_at?: string | null;
  current_period_ends_at?: string | null;
  usage: {
    active_users: number | null;
    active_stores?: number | null;
    active_sync_tasks?: number | null;
    listings?: number | null;
  };
  limits: {
    max_users: number | null;
    max_stores?: number | null;
    max_active_sync_tasks?: number | null;
    max_listings?: number | null;
  };
  warnings?: string[];
};

type AdminTenantActionResponse = {
  success: boolean;
  tenant?: AdminTenantSummary;
  user?: AdminUserDetail | null;
  admin_user?: AdminUserDetail | null;
  revoked_session_count?: number | null;
  feature_flag?: AdminFeatureFlag | null;
};

type CreateTenantFormState = {
  name: string;
  slug: string;
  plan: string;
  subscriptionStatus: string;
  adminUsername: string;
  adminEmail: string;
  adminPassword: string;
  reason: string;
};

type CreateTenantFormErrors = {
  name?: string;
  slug?: string;
  plan?: string;
  adminUsername?: string;
  adminEmail?: string;
  adminPassword?: string;
  reason?: string;
};

type SubscriptionFormState = {
  planName: string;
  subscriptionStatus: string;
  maxUsers: string;
  maxStores: string;
  maxActiveSyncTasks: string;
  maxListings: string;
  trialEndsAt: string;
  currentPeriodEndsAt: string;
  reason: string;
};

type SubscriptionFormErrors = {
  planName?: string;
  subscriptionStatus?: string;
  maxUsers?: string;
  maxStores?: string;
  maxActiveSyncTasks?: string;
  maxListings?: string;
  trialEndsAt?: string;
  currentPeriodEndsAt?: string;
  reason?: string;
};

type ActionDialogState = {
  open: boolean;
  title: string;
  riskText: string;
  confirmLabel: string;
  method: "POST" | "PATCH";
  path: string;
  body: Record<string, unknown>;
};

type CreateUserFormState = {
  username: string;
  email: string;
  role: string;
  password: string;
};

type ExpiryDialogState = {
  open: boolean;
  expiresAt: string;
  reason: string;
};

type CreateUserFormErrors = {
  username?: string;
  email?: string;
  password?: string;
};

type ExpiryDialogErrors = {
  expiresAt?: string;
  reason?: string;
};

type UserQueryOverride = {
  status?: string;
  role?: string;
  keyword?: string;
};

const DEFAULT_FEATURE_KEYS = ["admin", "selection"];
const DEFAULT_DIALOG_STATE: ActionDialogState = {
  open: false,
  title: "",
  riskText: "",
  confirmLabel: "Confirm",
  method: "POST",
  path: "",
  body: {},
};
const DEFAULT_CREATE_USER_FORM: CreateUserFormState = {
  username: "",
  email: "",
  role: "tenant_admin",
  password: "temp12345",
};
const DEFAULT_CREATE_TENANT_FORM: CreateTenantFormState = {
  name: "",
  slug: "",
  plan: "starter",
  subscriptionStatus: "active",
  adminUsername: "",
  adminEmail: "",
  adminPassword: "",
  reason: "customer onboarding",
};
const DEFAULT_SUBSCRIPTION_FORM: SubscriptionFormState = {
  planName: "",
  subscriptionStatus: "active",
  maxUsers: "",
  maxStores: "",
  maxActiveSyncTasks: "",
  maxListings: "",
  trialEndsAt: "",
  currentPeriodEndsAt: "",
  reason: "",
};
const DEFAULT_EXPIRY_DIALOG: ExpiryDialogState = {
  open: false,
  expiresAt: "",
  reason: "",
};

export default function AdminPage() {
  const [users, setUsers] = useState<AdminUserSummary[]>([]);
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  const [selectedUser, setSelectedUser] = useState<AdminUserDetail | null>(null);
  const [audits, setAudits] = useState<AdminAudit[]>([]);
  const [health, setHealth] = useState<SystemHealthResponse | null>(null);
  const [tenantUsage, setTenantUsage] = useState<TenantUsageResponse | AdminTenantUsageResponse | null>(null);
  const [tenants, setTenants] = useState<AdminTenantSummary[]>([]);
  const [selectedTenantId, setSelectedTenantId] = useState<string | null>(null);
  const [createTenantOpen, setCreateTenantOpen] = useState(false);
  const [createTenantForm, setCreateTenantForm] = useState<CreateTenantFormState>(DEFAULT_CREATE_TENANT_FORM);
  const [createTenantErrors, setCreateTenantErrors] = useState<CreateTenantFormErrors>({});
  const [createTenantShowValidation, setCreateTenantShowValidation] = useState(false);
  const [subscriptionForm, setSubscriptionForm] = useState<SubscriptionFormState>(DEFAULT_SUBSCRIPTION_FORM);
  const [subscriptionErrors, setSubscriptionErrors] = useState<SubscriptionFormErrors>({});
  const [subscriptionShowValidation, setSubscriptionShowValidation] = useState(false);
  const [statusFilter, setStatusFilter] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [keyword, setKeyword] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isMutating, setIsMutating] = useState(false);
  const [dialogState, setDialogState] = useState<ActionDialogState>(DEFAULT_DIALOG_STATE);
  const [dialogReason, setDialogReason] = useState("");
  const [createUserOpen, setCreateUserOpen] = useState(false);
  const [createUserForm, setCreateUserForm] = useState<CreateUserFormState>(DEFAULT_CREATE_USER_FORM);
  const [createUserErrors, setCreateUserErrors] = useState<CreateUserFormErrors>({});
  const [createUserShowValidation, setCreateUserShowValidation] = useState(false);
  const [expiryDialog, setExpiryDialog] = useState<ExpiryDialogState>(DEFAULT_EXPIRY_DIALOG);
  const [expiryErrors, setExpiryErrors] = useState<ExpiryDialogErrors>({});
  const [expiryShowValidation, setExpiryShowValidation] = useState(false);
  const [spotlightUserId, setSpotlightUserId] = useState<string | null>(null);
  const [timeAnchor, setTimeAnchor] = useState(() => Date.now());
  const userRowRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  async function loadSupportData() {
    const [auditData, healthData] = await Promise.all([
      apiFetch<AuditListResponse>("/admin/api/audits"),
      apiFetch<SystemHealthResponse>("/admin/api/system/health"),
    ]);
    setAudits(auditData.audits);
    setHealth(healthData);
  }

  async function loadTenantUsage(targetTenantId?: string | null) {
    if (!targetTenantId) {
      setTenantUsage(null);
      setSubscriptionForm(DEFAULT_SUBSCRIPTION_FORM);
      return;
    }

    const usageData = await apiFetch<AdminTenantUsageResponse>(
      `/admin/api/tenant/usage?tenant_id=${encodeURIComponent(targetTenantId)}`,
    );
    setTenantUsage(usageData);
    setSubscriptionForm({
      planName: usageData.plan ?? usageData.plan_name ?? "",
      subscriptionStatus: usageData.subscription_status ?? "active",
      maxUsers: toNullableNumberInput(usageData.limits.max_users),
      maxStores: toNullableNumberInput(usageData.limits.max_stores),
      maxActiveSyncTasks: toNullableNumberInput(usageData.limits.max_active_sync_tasks),
      maxListings: toNullableNumberInput(usageData.limits.max_listings),
      trialEndsAt: toDateTimeInputValue(usageData.trial_ends_at),
      currentPeriodEndsAt: toDateTimeInputValue(usageData.current_period_ends_at),
      reason: "",
    });
    setSubscriptionErrors({});
    setSubscriptionShowValidation(false);
  }

  async function loadTenants(targetTenantId?: string | null) {
    const tenantData = await apiFetch<AdminTenantsResponse>("/admin/api/tenants");
    setTenants(tenantData.tenants);

    const nextTenantId =
      targetTenantId && tenantData.tenants.some((tenant) => tenant.tenant_id === targetTenantId)
        ? targetTenantId
        : tenantData.tenants[0]?.tenant_id ?? null;

    setSelectedTenantId(nextTenantId);
    await loadTenantUsage(nextTenantId);
  }

  async function loadUsers(targetUserId?: string | null, overrides: UserQueryOverride = {}) {
    const params = new URLSearchParams();
    const nextStatus = overrides.status ?? statusFilter;
    const nextRole = overrides.role ?? roleFilter;
    const nextKeyword = overrides.keyword ?? keyword;
    if (nextStatus) params.set("status", nextStatus);
    if (nextRole) params.set("role", nextRole);
    if (nextKeyword.trim()) params.set("keyword", nextKeyword.trim());

    const path = params.size > 0 ? `/admin/api/users?${params.toString()}` : "/admin/api/users";
    const userData = await apiFetch<AdminUserListResponse>(path);
    setUsers(userData.users);

    const nextUserId =
      targetUserId && userData.users.some((user) => user.user_id === targetUserId)
        ? targetUserId
        : userData.users[0]?.user_id ?? null;

    setSelectedUserId(nextUserId);
    if (nextUserId) {
      const detail = await apiFetch<AdminUserDetail>(`/admin/api/users/${nextUserId}`);
      setSelectedUser(detail);
    } else {
      setSelectedUser(null);
    }
  }

  function resetFeedback() {
    setErrorMessage("");
    setSuccessMessage("");
  }

  async function loadData(targetUserId?: string | null, overrides: UserQueryOverride = {}) {
    setIsLoading(true);
    setErrorMessage("");

    try {
      await Promise.all([
        loadSupportData(),
        loadUsers(targetUserId ?? selectedUserId, overrides),
        loadTenants(selectedTenantId),
      ]);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "加载管理数据失败");
    } finally {
      setIsLoading(false);
    }
  }

  async function selectUser(userId: string) {
    try {
      const detail = await apiFetch<AdminUserDetail>(`/admin/api/users/${userId}`);
      setSelectedUserId(userId);
      setSelectedUser(detail);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "加载用户详情失败");
    }
  }

  function toUserSummary(user: AdminUserDetail): AdminUserSummary {
    return {
      user_id: user.user_id,
      username: user.username,
      email: user.email,
      role: user.role,
      status: user.status,
      expires_at: user.expires_at,
      subscription_status: user.subscription_status,
      feature_flags: user.feature_flags,
      active_session_count: user.active_session_count,
    };
  }

  function applyUserSnapshot(user: AdminUserDetail, prepend = false) {
    const summary = toUserSummary(user);
    setUsers((currentUsers) => {
      const existingIndex = currentUsers.findIndex((currentUser) => currentUser.user_id === user.user_id);
      if (prepend || existingIndex === -1) {
        return [summary, ...currentUsers.filter((currentUser) => currentUser.user_id !== user.user_id)];
      }
      const nextUsers = [...currentUsers];
      nextUsers[existingIndex] = summary;
      return nextUsers;
    });
    setSelectedUserId(user.user_id);
    setSelectedUser(user);
    setSpotlightUserId(user.user_id);
  }

  function refreshAdminDataInBackground(targetUserId?: string | null, overrides: UserQueryOverride = {}) {
    void Promise.all([
      loadSupportData(),
      loadUsers(targetUserId ?? selectedUserId, overrides),
      loadTenants(selectedTenantId),
    ]).catch((error) => {
      setErrorMessage(error instanceof Error ? error.message : "刷新管理数据失败");
    });
  }

  function openActionDialog(config: Omit<ActionDialogState, "open" | "method"> & { method?: ActionDialogState["method"] }) {
    resetFeedback();
    setCreateUserOpen(false);
    setCreateUserShowValidation(false);
    setCreateUserErrors({});
    setExpiryDialog(DEFAULT_EXPIRY_DIALOG);
    setExpiryShowValidation(false);
    setExpiryErrors({});
    setDialogReason("");
    setDialogState({ open: true, method: config.method ?? "POST", ...config });
  }

  function closeActionDialog() {
    setDialogReason("");
    setDialogState(DEFAULT_DIALOG_STATE);
  }

  function openCreateUserDialog() {
    resetFeedback();
    setExpiryDialog(DEFAULT_EXPIRY_DIALOG);
    setExpiryShowValidation(false);
    setExpiryErrors({});
    closeActionDialog();
    setCreateUserForm(DEFAULT_CREATE_USER_FORM);
    setCreateUserShowValidation(false);
    setCreateUserErrors({});
    setCreateUserOpen(true);
  }

  function closeCreateUserDialog() {
    setCreateUserOpen(false);
    setCreateUserForm(DEFAULT_CREATE_USER_FORM);
    setCreateUserShowValidation(false);
    setCreateUserErrors({});
  }

  function setCreateTenantField<K extends keyof CreateTenantFormState>(field: K, value: CreateTenantFormState[K]) {
    const nextForm = { ...createTenantForm, [field]: value };
    setCreateTenantForm(nextForm);
    if (createTenantShowValidation) {
      setCreateTenantErrors(validateCreateTenantForm(nextForm));
    }
  }

  function setSubscriptionField<K extends keyof SubscriptionFormState>(field: K, value: SubscriptionFormState[K]) {
    const nextForm = { ...subscriptionForm, [field]: value };
    setSubscriptionForm(nextForm);
    if (subscriptionShowValidation) {
      setSubscriptionErrors(validateSubscriptionForm(nextForm));
    }
  }

  function openExpiryDialog() {
    if (!selectedUser) return;
    resetFeedback();
    setCreateUserOpen(false);
    setCreateUserShowValidation(false);
    setCreateUserErrors({});
    closeActionDialog();
    setExpiryDialog({
      open: true,
      expiresAt: toDateTimeInputValue(selectedUser.expires_at),
      reason: "",
    });
    setExpiryShowValidation(false);
    setExpiryErrors({});
  }

  function closeExpiryDialog() {
    setExpiryDialog(DEFAULT_EXPIRY_DIALOG);
    setExpiryShowValidation(false);
    setExpiryErrors({});
  }

  function setCreateUserField<K extends keyof CreateUserFormState>(field: K, value: CreateUserFormState[K]) {
    const nextForm = { ...createUserForm, [field]: value };
    setCreateUserForm(nextForm);
    if (createUserShowValidation) {
      setCreateUserErrors(validateCreateUserForm(nextForm));
    }
  }

  function setExpiryField<K extends keyof Omit<ExpiryDialogState, "open">>(
    field: K,
    value: ExpiryDialogState[K],
  ) {
    const nextDialog = { ...expiryDialog, [field]: value };
    setExpiryDialog(nextDialog);
    if (expiryShowValidation) {
      setExpiryErrors(validateExpiryDialog(nextDialog));
    }
  }

  async function submitCreateUser() {
    const nextErrors = validateCreateUserForm(createUserForm);
    setCreateUserShowValidation(true);
    setCreateUserErrors(nextErrors);
    if (hasValidationErrors(nextErrors)) {
      return;
    }

    setIsMutating(true);
    resetFeedback();

    try {
      const response = await apiFetch<AdminActionResponse>("/admin/api/users", {
        method: "POST",
        body: JSON.stringify({
          username: createUserForm.username.trim(),
          email: createUserForm.email.trim() || null,
          role: createUserForm.role,
          password: createUserForm.password,
        }),
      });
      const createdUser = response.user;
      if (!createdUser) {
        throw new Error("创建用户返回数据缺失");
      }
      closeCreateUserDialog();
      setStatusFilter("");
      setRoleFilter("");
      setKeyword("");
      applyUserSnapshot(createdUser, true);
      setIsLoading(false);
      setSuccessMessage(`已创建用户 ${createdUser.username}。`);
      refreshAdminDataInBackground(createdUser.user_id, { status: "", role: "", keyword: "" });
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "创建用户失败");
    } finally {
      setIsMutating(false);
    }
  }

  async function submitCreateTenant() {
    const nextErrors = validateCreateTenantForm(createTenantForm);
    setCreateTenantShowValidation(true);
    setCreateTenantErrors(nextErrors);
    if (hasValidationErrors(nextErrors)) {
      return;
    }

    setIsMutating(true);
    resetFeedback();

    try {
      const response = await apiFetch<{ tenant?: AdminTenantSummary }>("/admin/api/tenants", {
        method: "POST",
        body: JSON.stringify({
          name: createTenantForm.name.trim(),
          slug: createTenantForm.slug.trim(),
          plan: createTenantForm.plan.trim(),
          subscription_status: createTenantForm.subscriptionStatus,
          admin_username: createTenantForm.adminUsername.trim(),
          admin_email: createTenantForm.adminEmail.trim() || null,
          admin_password: createTenantForm.adminPassword.trim(),
          reason: createTenantForm.reason.trim(),
        }),
      });
      setCreateTenantOpen(false);
      setCreateTenantForm(DEFAULT_CREATE_TENANT_FORM);
      await loadTenants(response.tenant?.tenant_id ?? selectedTenantId);
      setSuccessMessage(`已创建租户 ${createTenantForm.name.trim()}。`);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "创建租户失败");
    } finally {
      setIsMutating(false);
    }
  }

  async function submitSubscriptionUpdate() {
    const nextErrors = validateSubscriptionForm(subscriptionForm);
    setSubscriptionShowValidation(true);
    setSubscriptionErrors(nextErrors);
    if (!selectedTenantId || hasValidationErrors(nextErrors)) {
      return;
    }

    setIsMutating(true);
    resetFeedback();

    try {
      await apiFetch<{ tenant?: AdminTenantSummary; usage?: AdminTenantUsageResponse }>(
        `/admin/api/tenants/${selectedTenantId}/subscription`,
        {
          method: "PATCH",
          body: JSON.stringify({
            plan: subscriptionForm.planName.trim(),
            status: subscriptionForm.subscriptionStatus,
            limits: {
              max_users: parseNullableInteger(subscriptionForm.maxUsers),
              max_stores: parseNullableInteger(subscriptionForm.maxStores),
              max_active_sync_tasks: parseNullableInteger(subscriptionForm.maxActiveSyncTasks),
              max_listings: parseNullableInteger(subscriptionForm.maxListings),
            },
            trial_ends_at: subscriptionForm.trialEndsAt
              ? new Date(subscriptionForm.trialEndsAt).toISOString()
              : null,
            current_period_ends_at: subscriptionForm.currentPeriodEndsAt
              ? new Date(subscriptionForm.currentPeriodEndsAt).toISOString()
              : null,
            reason: subscriptionForm.reason.trim(),
          }),
        },
      );
      await loadTenants(selectedTenantId);
      setSuccessMessage("已更新租户订阅。");
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "更新租户订阅失败");
    } finally {
      setIsMutating(false);
    }
  }

  async function submitExpiry() {
    const nextErrors = validateExpiryDialog(expiryDialog);
    setExpiryShowValidation(true);
    setExpiryErrors(nextErrors);
    if (!selectedUser || hasValidationErrors(nextErrors)) {
      return;
    }

    setIsMutating(true);
    resetFeedback();

    try {
      const response = await apiFetch<AdminActionResponse>(`/admin/api/users/${selectedUser.user_id}/set-expiry`, {
        method: "POST",
        body: JSON.stringify({
          expires_at: expiryDialog.expiresAt ? new Date(expiryDialog.expiresAt).toISOString() : null,
          reason: expiryDialog.reason.trim(),
        }),
      });
      closeExpiryDialog();
      if (response.user) {
        applyUserSnapshot(response.user);
      }
      setSuccessMessage(
        expiryDialog.expiresAt
          ? `已更新 ${selectedUser.username} 的到期时间。`
          : `已清除 ${selectedUser.username} 的到期时间。`,
      );
      refreshAdminDataInBackground(selectedUser.user_id);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "更新到期时间失败");
    } finally {
      setIsMutating(false);
    }
  }

  async function confirmAction() {
    if (!dialogState.path || !dialogReason.trim()) {
      return;
    }

    setIsMutating(true);
    setErrorMessage("");

    try {
      const response = await apiFetch<AdminActionResponse & Partial<AdminTenantActionResponse>>(dialogState.path, {
        method: dialogState.method,
        body: JSON.stringify({
          ...dialogState.body,
          reason: dialogReason.trim(),
        }),
      });
      const responseUser = response.user ?? response.admin_user ?? null;
      if (responseUser) {
        applyUserSnapshot(responseUser);
      }
      if (response.tenant) {
        setSelectedTenantId(response.tenant.tenant_id);
        await loadTenants(response.tenant.tenant_id);
      }
      setSuccessMessage(
        response.feature_flag
          ? `${response.feature_flag.feature_key} 已${response.feature_flag.enabled ? "开启" : "关闭"}，用户：${response.user?.username ?? selectedUser?.username ?? "user"}。`
          : response.tenant
            ? `${dialogState.confirmLabel} 已完成，租户：${response.tenant.name}。`
            : `${dialogState.confirmLabel} 已完成，用户：${responseUser?.username ?? selectedUser?.username ?? "user"}。`,
      );
      closeActionDialog();
      if (!response.tenant) {
        refreshAdminDataInBackground(responseUser?.user_id ?? selectedUserId);
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "管理操作失败");
    } finally {
      setIsMutating(false);
    }
  }

  useEffect(() => {
    void loadData();
  }, [statusFilter, roleFilter, keyword]);

  useEffect(() => {
    const intervalId = window.setInterval(() => {
      setTimeAnchor(Date.now());
    }, 1000);
    return () => window.clearInterval(intervalId);
  }, []);

  useEffect(() => {
    if (!selectedUserId) return;
    const target = userRowRefs.current[selectedUserId];
    if (!target) return;
    target.focus({ preventScroll: true });
    target.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selectedUserId, users]);

  useEffect(() => {
    if (!spotlightUserId) return;
    const timeoutId = window.setTimeout(() => {
      setSpotlightUserId((current) => (current === spotlightUserId ? null : current));
    }, 2200);
    return () => window.clearTimeout(timeoutId);
  }, [spotlightUserId]);

  const selectedUserSummary = useMemo(
    () => users.find((user) => user.user_id === selectedUserId) ?? null,
    [selectedUserId, users],
  );
  const selectedTenant = useMemo(
    () => tenants.find((tenant) => tenant.tenant_id === selectedTenantId) ?? null,
    [selectedTenantId, tenants],
  );

  const featureFlags = useMemo(() => {
    const existing = new Map<string, AdminFeatureFlag>();
    for (const flag of selectedUser?.feature_flags ?? []) {
      existing.set(flag.feature_key, flag);
    }
    return Array.from(new Set([...DEFAULT_FEATURE_KEYS, ...existing.keys()])).map((featureKey) => ({
      feature_key: featureKey,
      enabled: existing.get(featureKey)?.enabled ?? false,
      source: existing.get(featureKey)?.source ?? "default",
      updated_at: existing.get(featureKey)?.updated_at,
    }));
  }, [selectedUser]);

  const dbHealth = useMemo(
    () => health?.components.find((component) => component.component === "db") ?? null,
    [health],
  );

  const selectedDisplayStatus = resolveUserStatus(
    selectedUser?.status ?? selectedUserSummary?.status,
    selectedUser?.expires_at ?? selectedUserSummary?.expires_at,
    timeAnchor,
  );
  const canDisableSelectedUser = selectedDisplayStatus === "active" || selectedDisplayStatus === "expired";

  return (
    <>
      <div style={pageStyle}>
        <section style={sidebarStyle}>
          <div style={sectionHeaderStyle}>
            <div>
              <div style={eyebrowStyle}>平台 / 用户</div>
              <div style={sectionTitleStyle}>用户与权限</div>
            </div>
            <div style={{ display: "grid", gap: 8, justifyItems: "end" }}>
              <button type="button" style={primaryButtonStyle} onClick={openCreateUserDialog} data-testid="open-create-user">
                新建用户
              </button>
              <div style={mutedTextStyle}>{users.length} 个用户</div>
            </div>
          </div>

          <div style={{ display: "grid", gap: 10 }}>
            <input
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              placeholder="搜索用户名或邮箱"
              style={inputStyle}
            />
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} style={inputStyle}>
                <option value="">全部状态</option>
                <option value="active">正常</option>
                <option value="disabled">已停用</option>
                <option value="pending">待处理</option>
                <option value="locked">已锁定</option>
                <option value="expired">已过期</option>
              </select>
              <select value={roleFilter} onChange={(event) => setRoleFilter(event.target.value)} style={inputStyle}>
                <option value="">全部角色</option>
                <option value="super_admin">超级管理员</option>
                <option value="tenant_admin">租户管理员</option>
                <option value="operator">运营</option>
                <option value="warehouse">仓库</option>
              </select>
            </div>
          </div>

          {errorMessage ? <div style={errorStyle}>{errorMessage}</div> : null}
          {successMessage ? (
            <div style={successStyle} data-testid="admin-success-banner">
              {successMessage}
            </div>
          ) : null}
          {isLoading ? <div style={mutedTextStyle}>正在加载用户...</div> : null}

          <div style={{ display: "grid", gap: 10 }}>
            {users.map((user) => {
              const displayStatus = resolveUserStatus(user.status, user.expires_at, timeAnchor);
              const isSelected = user.user_id === selectedUserId;
              const isSpotlighted = user.user_id === spotlightUserId;
              return (
                <button
                  key={user.user_id}
                  ref={(node) => {
                    userRowRefs.current[user.user_id] = node;
                  }}
                  type="button"
                  data-testid={`user-row-${user.username}`}
                  onClick={() => void selectUser(user.user_id)}
                  style={{
                    ...userCardStyle,
                    borderColor: isSelected || isSpotlighted ? "#000000" : "#EBEBEB",
                    background: isSpotlighted ? "#FAFAFA" : "#ffffff",
                    boxShadow: "none",
                    transform: isSpotlighted ? "translateY(-1px)" : "none",
                    transition: "box-shadow 180ms ease, transform 180ms ease, background 180ms ease",
                  }}
                >
                  <div style={{ display: "grid", gap: 4 }}>
                    <strong>{user.username}</strong>
                    <span style={mutedTextStyle}>
                      {user.role} / {getStatusLabel(displayStatus)}
                    </span>
                  </div>
                  <div style={pillRowStyle}>
                    <span style={statusPillStyle(displayStatus ?? "pending")}>{getStatusLabel(displayStatus)}</span>
                    {user.feature_flags.map((flag) => (
                      <span key={flag.feature_key} style={flagPillStyle(flag.enabled)}>
                        {flag.feature_key}
                      </span>
                    ))}
                  </div>
                </button>
              );
            })}
          </div>
        </section>

        <section style={detailStyle}>
          <div style={sectionHeaderStyle}>
            <div>
              <div style={eyebrowStyle}>用户详情</div>
              <div style={sectionTitleStyle}>
                {selectedUser?.username ?? "选择一个用户"}
              </div>
            </div>
            {selectedDisplayStatus ? (
              <span style={statusPillStyle(selectedDisplayStatus)} data-testid="selected-user-status">
                {getStatusLabel(selectedDisplayStatus)}
              </span>
            ) : null}
          </div>

          {selectedUser ? (
            <div style={{ display: "grid", gap: 16 }}>
              <div style={gridStyle}>
                <MetricCard label="角色" value={formatRole(selectedUser.role)} />
                <MetricCard
                  label="活跃会话"
                  value={String(selectedUser.active_session_count)}
                />
                <MetricCard
                  label="强制重置"
                  value={selectedUser.force_password_reset ? "是" : "否"}
                />
                <MetricCard
                  label="最近登录"
                  value={formatDateTime(selectedUser.last_login_at)}
                />
              </div>

              <section style={subPanelStyle}>
                <div style={sectionHeaderStyle}>
                  <div style={subSectionTitleStyle}>账号信息</div>
                  <button type="button" style={buttonStyle} onClick={openExpiryDialog} data-testid="open-expiry-dialog">
                    设置到期
                  </button>
                </div>
                <div style={propertyGridStyle}>
                  <Property label="用户 ID" value={selectedUser.user_id} />
                  <Property label="邮箱" value={selectedUser.email ?? "--"} />
                  <Property label="订阅状态" value={formatSubscriptionStatus(selectedUser.subscription_status)} />
                  <Property label="到期时间" value={formatDateTime(selectedUser.expires_at)} />
                  <Property label="创建时间" value={formatDateTime(selectedUser.created_at)} />
                  <Property label="更新时间" value={formatDateTime(selectedUser.updated_at)} />
                </div>
              </section>

              <section style={subPanelStyle}>
                <div style={subSectionTitleStyle}>功能开关</div>
                <div style={{ display: "grid", gap: 10 }}>
                  {featureFlags.map((flag) => (
                    <div key={flag.feature_key} style={featureFlagRowStyle}>
                      <div style={{ display: "grid", gap: 4 }}>
                        <strong>{flag.feature_key}</strong>
                        <span style={mutedTextStyle}>
                          {flag.enabled ? "已开启" : "已关闭"} / 来源：{flag.source}
                        </span>
                      </div>
                      <button
                        type="button"
                        style={buttonStyle}
                        data-testid={`feature-flag-toggle-${flag.feature_key}`}
                        onClick={() =>
                          openActionDialog({
                            title: `调整 ${flag.feature_key}`,
                            riskText: `这会修改 ${selectedUser.username} 的 ${flag.feature_key} 能力，并记录为高危管理审计。`,
                            confirmLabel: flag.enabled ? "关闭开关" : "开启开关",
                            path: `/admin/api/users/${selectedUser.user_id}/feature-flags`,
                            body: {
                              feature_key: flag.feature_key,
                              enabled: !flag.enabled,
                            },
                          })
                        }
                      >
                        {flag.enabled ? "关闭" : "开启"}
                      </button>
                    </div>
                  ))}
                </div>
              </section>

              <section style={subPanelStyle}>
                <div style={subSectionTitleStyle}>高危操作</div>
                <div style={actionGridStyle}>
                  <button
                    type="button"
                    style={buttonStyle}
                    onClick={() =>
                      openActionDialog({
                        title: "重置密码",
                        riskText: `重置 ${selectedUser.username} 的密码会强制凭证轮换，并写入高危审计日志。`,
                        confirmLabel: "确认重置密码",
                        path: `/admin/api/users/${selectedUser.user_id}/reset-password`,
                        body: {},
                      })
                    }
                  >
                    重置密码
                  </button>

                  <button
                    type="button"
                    style={buttonStyle}
                    onClick={() =>
                      openActionDialog({
                        title: canDisableSelectedUser ? "停用用户" : "启用用户",
                        riskText:
                          canDisableSelectedUser
                            ? `停用 ${selectedUser.username} 会撤销访问权限，仅用于明确的人工介入场景。`
                            : `启用 ${selectedUser.username} 会恢复访问权限，操作前应确认交付策略允许。`,
                        confirmLabel: canDisableSelectedUser ? "确认停用用户" : "确认启用用户",
                        path:
                          canDisableSelectedUser
                            ? `/admin/api/users/${selectedUser.user_id}/disable`
                            : `/admin/api/users/${selectedUser.user_id}/enable`,
                        body: {},
                      })
                    }
                  >
                    {canDisableSelectedUser ? "停用用户" : "启用用户"}
                  </button>

                  <button
                    type="button"
                    style={buttonStyle}
                    onClick={() =>
                      openActionDialog({
                        title: "强制下线",
                        riskText: `强制下线会撤销 ${selectedUser.username} 的所有活跃会话。`,
                        confirmLabel: "确认强制下线",
                        path: `/admin/api/users/${selectedUser.user_id}/force-logout`,
                        body: {},
                      })
                    }
                  >
                    强制下线
                  </button>
                </div>
              </section>
            </div>
          ) : (
            <div style={emptyStateStyle}>从左侧选择一个用户查看详情。</div>
          )}

          <section style={subPanelStyle}>
            <div style={sectionHeaderStyle}>
              <div>
                <div style={eyebrowStyle}>平台 / 租户</div>
                <div style={sectionTitleStyle}>租户管理</div>
              </div>
              <button
                type="button"
                style={primaryButtonStyle}
                onClick={() => setCreateTenantOpen((current) => !current)}
                data-testid="toggle-create-tenant"
              >
                {createTenantOpen ? "收起表单" : "新建租户"}
              </button>
            </div>

            {createTenantOpen ? (
              <section style={subPanelStyle}>
                <div style={subSectionTitleStyle}>新建租户</div>
                <div style={dialogFormGridStyle}>
                  <label style={fieldStyle}>
                    <span style={fieldLabelStyle}>租户名称</span>
                    <input
                      value={createTenantForm.name}
                      onChange={(event) => setCreateTenantField("name", event.target.value)}
                      placeholder="Acme CN"
                      aria-invalid={Boolean(createTenantErrors.name)}
                      style={getInputFieldStyle(Boolean(createTenantErrors.name))}
                    />
                    {createTenantErrors.name ? <span style={fieldErrorTextStyle}>{createTenantErrors.name}</span> : null}
                  </label>
                  <label style={fieldStyle}>
                    <span style={fieldLabelStyle}>租户标识</span>
                    <input
                      value={createTenantForm.slug}
                      onChange={(event) => setCreateTenantField("slug", event.target.value)}
                      placeholder="acme-cn"
                      aria-invalid={Boolean(createTenantErrors.slug)}
                      style={getInputFieldStyle(Boolean(createTenantErrors.slug))}
                    />
                    {createTenantErrors.slug ? <span style={fieldErrorTextStyle}>{createTenantErrors.slug}</span> : null}
                  </label>
                  <label style={fieldStyle}>
                    <span style={fieldLabelStyle}>订阅状态</span>
                    <select
                      value={createTenantForm.subscriptionStatus}
                      onChange={(event) => setCreateTenantField("subscriptionStatus", event.target.value)}
                      style={inputStyle}
                    >
                      <option value="active">正常</option>
                      <option value="trialing">试用中</option>
                      <option value="paused">已暂停</option>
                    </select>
                  </label>
                  <label style={fieldStyle}>
                    <span style={fieldLabelStyle}>初始套餐</span>
                    <input
                      value={createTenantForm.plan}
                      onChange={(event) => setCreateTenantField("plan", event.target.value)}
                      placeholder="starter"
                      aria-invalid={Boolean(createTenantErrors.plan)}
                      style={getInputFieldStyle(Boolean(createTenantErrors.plan))}
                    />
                    {createTenantErrors.plan ? <span style={fieldErrorTextStyle}>{createTenantErrors.plan}</span> : null}
                  </label>
                  <label style={fieldStyle}>
                    <span style={fieldLabelStyle}>管理员账号</span>
                    <input
                      value={createTenantForm.adminUsername}
                      onChange={(event) => setCreateTenantField("adminUsername", event.target.value)}
                      placeholder="acme_admin"
                      aria-invalid={Boolean(createTenantErrors.adminUsername)}
                      style={getInputFieldStyle(Boolean(createTenantErrors.adminUsername))}
                    />
                    {createTenantErrors.adminUsername ? <span style={fieldErrorTextStyle}>{createTenantErrors.adminUsername}</span> : null}
                  </label>
                  <label style={fieldStyle}>
                    <span style={fieldLabelStyle}>管理员邮箱</span>
                    <input
                      value={createTenantForm.adminEmail}
                      onChange={(event) => setCreateTenantField("adminEmail", event.target.value)}
                      placeholder="admin@example.com"
                      aria-invalid={Boolean(createTenantErrors.adminEmail)}
                      style={getInputFieldStyle(Boolean(createTenantErrors.adminEmail))}
                    />
                    {createTenantErrors.adminEmail ? <span style={fieldErrorTextStyle}>{createTenantErrors.adminEmail}</span> : null}
                  </label>
                  <label style={fieldStyle}>
                    <span style={fieldLabelStyle}>初始密码</span>
                    <input
                      type="password"
                      value={createTenantForm.adminPassword}
                      onChange={(event) => setCreateTenantField("adminPassword", event.target.value)}
                      placeholder="至少 8 个字符"
                      aria-invalid={Boolean(createTenantErrors.adminPassword)}
                      style={getInputFieldStyle(Boolean(createTenantErrors.adminPassword))}
                    />
                    {createTenantErrors.adminPassword ? <span style={fieldErrorTextStyle}>{createTenantErrors.adminPassword}</span> : null}
                  </label>
                  <label style={fieldStyle}>
                    <span style={fieldLabelStyle}>操作原因</span>
                    <input
                      value={createTenantForm.reason}
                      onChange={(event) => setCreateTenantField("reason", event.target.value)}
                      placeholder="客户开通"
                      aria-invalid={Boolean(createTenantErrors.reason)}
                      style={getInputFieldStyle(Boolean(createTenantErrors.reason))}
                    />
                    {createTenantErrors.reason ? <span style={fieldErrorTextStyle}>{createTenantErrors.reason}</span> : null}
                  </label>
                </div>
                <div style={dialogFooterStyle}>
                  <button type="button" style={buttonStyle} onClick={() => setCreateTenantOpen(false)} disabled={isMutating}>
                    取消
                  </button>
                  <button type="button" style={primaryButtonStyle} onClick={() => void submitCreateTenant()} disabled={isMutating}>
                    {isMutating ? "创建中..." : "创建租户"}
                  </button>
                </div>
              </section>
            ) : null}

            <div style={tenantWorkspaceStyle}>
              <div style={{ display: "grid", gap: 10 }}>
                {tenants.length > 0 ? (
                  tenants.map((tenant) => {
                    const isSelected = tenant.tenant_id === selectedTenantId;
                    return (
                      <button
                        key={tenant.tenant_id}
                        type="button"
                        onClick={() => {
                          setSelectedTenantId(tenant.tenant_id);
                          void loadTenantUsage(tenant.tenant_id);
                        }}
                        style={{
                          ...userCardStyle,
                          borderColor: isSelected ? "#000000" : "#EBEBEB",
                          boxShadow: "none",
                        }}
                      >
                        <div style={{ display: "grid", gap: 4 }}>
                          <strong>{tenant.name}</strong>
                          <span style={mutedTextStyle}>/{tenant.slug}</span>
                        </div>
                        <div style={pillRowStyle}>
                          <span style={statusPillStyle(tenant.status)}>{tenant.status}</span>
                          <span style={flagPillStyle(Boolean(tenant.plan_name))}>{tenant.plan_name ?? "--"}</span>
                        </div>
                      </button>
                    );
                  })
                ) : (
                  <div style={emptyStateStyle}>暂无租户。创建第一个租户后即可配置订阅控制。</div>
                )}
              </div>

              <div style={{ display: "grid", gap: 16 }}>
                {selectedTenant ? (
                  <>
                    <div style={gridStyle}>
                      <MetricCard label="套餐" value={selectedTenant.plan_name ?? "--"} />
                      <MetricCard label="状态" value={getStatusLabel(selectedTenant.status)} />
                      <MetricCard label="订阅" value={formatSubscriptionStatus(selectedTenant.subscription_status)} />
                      <MetricCard label="剩余额度" value={formatRemainingSummary(tenantUsage)} />
                    </div>

                    <section style={subPanelStyle}>
                      <div style={subSectionTitleStyle}>租户快照</div>
                      <div style={propertyGridStyle}>
                        <Property label="名称" value={selectedTenant.name} />
                        <Property label="标识" value={selectedTenant.slug} />
                        <Property label="租户 ID" value={selectedTenant.tenant_id} />
                        <Property label="用量" value={formatUsageSummary(tenantUsage)} />
                        <Property label="试用到期" value={formatDateTime(selectedTenant.trial_ends_at ?? tenantUsage?.trial_ends_at)} />
                        <Property
                          label="付费有效期"
                          value={formatDateTime(selectedTenant.current_period_ends_at ?? tenantUsage?.current_period_ends_at)}
                        />
                        <Property label="创建时间" value={formatDateTime(selectedTenant.created_at)} />
                        <Property label="更新时间" value={formatDateTime(selectedTenant.updated_at)} />
                      </div>
                      {(tenantUsage?.warnings ?? []).map((warning) => (
                        <div key={warning} style={warningStyle}>
                          {warning}
                        </div>
                      ))}
                      <div style={tenantActionRowStyle}>
                        {selectedTenant.status === "active" ? (
                          <>
                            <button
                              type="button"
                              style={buttonStyle}
                              onClick={() =>
                                openActionDialog({
                                  title: "暂停租户",
                                  riskText: `暂停 ${selectedTenant.name} 会立即撤销租户会话，并阻止登录直到恢复。`,
                                  confirmLabel: "确认暂停租户",
                                  method: "PATCH",
                                  path: `/admin/api/tenants/${selectedTenant.tenant_id}`,
                                  body: { status: "suspended" },
                                })
                              }
                            >
                              暂停
                            </button>
                            <button
                              type="button"
                              style={buttonStyle}
                              onClick={() =>
                                openActionDialog({
                                  title: "停用租户",
                                  riskText: `停用 ${selectedTenant.name} 是硬停机操作，会撤销会话并阻止访问直到恢复。`,
                                  confirmLabel: "确认停用租户",
                                  method: "PATCH",
                                  path: `/admin/api/tenants/${selectedTenant.tenant_id}`,
                                  body: { status: "disabled" },
                                })
                              }
                            >
                              停用
                            </button>
                          </>
                        ) : (
                          <button
                            type="button"
                            style={primaryButtonStyle}
                            onClick={() =>
                              openActionDialog({
                                title: "恢复租户",
                                riskText: `恢复 ${selectedTenant.name} 会在当前订阅策略下重新开放登录和写入权限。`,
                                confirmLabel: "确认恢复租户",
                                method: "PATCH",
                                path: `/admin/api/tenants/${selectedTenant.tenant_id}`,
                                body: { status: "active" },
                              })
                            }
                          >
                            恢复
                          </button>
                        )}
                        <button
                          type="button"
                          style={buttonStyle}
                          onClick={() =>
                            openActionDialog({
                              title: "重置租户管理员密码",
                              riskText: `这会重置 ${selectedTenant.name} 第一个活跃租户管理员的临时密码，并撤销该管理员会话。`,
                              confirmLabel: "确认重置管理员",
                              path: `/admin/api/tenants/${selectedTenant.tenant_id}/reset-admin-password`,
                              body: {},
                            })
                          }
                        >
                          重置租户管理员
                        </button>
                      </div>
                    </section>

                    <section style={subPanelStyle}>
                      <div style={subSectionTitleStyle}>调整订阅</div>
                      <div style={dialogFormGridStyle}>
                        <label style={fieldStyle}>
                          <span style={fieldLabelStyle}>套餐</span>
                          <input
                            value={subscriptionForm.planName}
                            onChange={(event) => setSubscriptionField("planName", event.target.value)}
                            placeholder="growth"
                            aria-invalid={Boolean(subscriptionErrors.planName)}
                            style={getInputFieldStyle(Boolean(subscriptionErrors.planName))}
                          />
                          {subscriptionErrors.planName ? (
                            <span style={fieldErrorTextStyle}>{subscriptionErrors.planName}</span>
                          ) : null}
                        </label>
                        <label style={fieldStyle}>
                          <span style={fieldLabelStyle}>订阅状态</span>
                          <select
                            value={subscriptionForm.subscriptionStatus}
                            onChange={(event) => setSubscriptionField("subscriptionStatus", event.target.value)}
                            style={inputStyle}
                          >
                            <option value="active">正常</option>
                            <option value="trialing">试用中</option>
                            <option value="past_due">逾期</option>
                            <option value="paused">已暂停</option>
                            <option value="cancelled">已取消</option>
                          </select>
                        </label>
                        <label style={fieldStyle}>
                          <span style={fieldLabelStyle}>试用到期</span>
                          <input
                            type="datetime-local"
                            value={subscriptionForm.trialEndsAt}
                            onChange={(event) => setSubscriptionField("trialEndsAt", event.target.value)}
                            aria-invalid={Boolean(subscriptionErrors.trialEndsAt)}
                            style={getInputFieldStyle(Boolean(subscriptionErrors.trialEndsAt))}
                          />
                          {subscriptionErrors.trialEndsAt ? (
                            <span style={fieldErrorTextStyle}>{subscriptionErrors.trialEndsAt}</span>
                          ) : null}
                        </label>
                        <label style={fieldStyle}>
                          <span style={fieldLabelStyle}>付费有效期</span>
                          <input
                            type="datetime-local"
                            value={subscriptionForm.currentPeriodEndsAt}
                            onChange={(event) => setSubscriptionField("currentPeriodEndsAt", event.target.value)}
                            aria-invalid={Boolean(subscriptionErrors.currentPeriodEndsAt)}
                            style={getInputFieldStyle(Boolean(subscriptionErrors.currentPeriodEndsAt))}
                          />
                          {subscriptionErrors.currentPeriodEndsAt ? (
                            <span style={fieldErrorTextStyle}>{subscriptionErrors.currentPeriodEndsAt}</span>
                          ) : null}
                        </label>
                        <label style={fieldStyle}>
                          <span style={fieldLabelStyle}>用户上限</span>
                          <input
                            value={subscriptionForm.maxUsers}
                            onChange={(event) => setSubscriptionField("maxUsers", event.target.value)}
                            placeholder="50"
                            aria-invalid={Boolean(subscriptionErrors.maxUsers)}
                            style={getInputFieldStyle(Boolean(subscriptionErrors.maxUsers))}
                          />
                          {subscriptionErrors.maxUsers ? <span style={fieldErrorTextStyle}>{subscriptionErrors.maxUsers}</span> : null}
                        </label>
                        <label style={fieldStyle}>
                          <span style={fieldLabelStyle}>店铺上限</span>
                          <input
                            value={subscriptionForm.maxStores}
                            onChange={(event) => setSubscriptionField("maxStores", event.target.value)}
                            placeholder="10"
                            aria-invalid={Boolean(subscriptionErrors.maxStores)}
                            style={getInputFieldStyle(Boolean(subscriptionErrors.maxStores))}
                          />
                          {subscriptionErrors.maxStores ? (
                            <span style={fieldErrorTextStyle}>{subscriptionErrors.maxStores}</span>
                          ) : null}
                        </label>
                        <label style={fieldStyle}>
                          <span style={fieldLabelStyle}>同步任务上限</span>
                          <input
                            value={subscriptionForm.maxActiveSyncTasks}
                            onChange={(event) => setSubscriptionField("maxActiveSyncTasks", event.target.value)}
                            placeholder="4"
                            aria-invalid={Boolean(subscriptionErrors.maxActiveSyncTasks)}
                            style={getInputFieldStyle(Boolean(subscriptionErrors.maxActiveSyncTasks))}
                          />
                          {subscriptionErrors.maxActiveSyncTasks ? (
                            <span style={fieldErrorTextStyle}>{subscriptionErrors.maxActiveSyncTasks}</span>
                          ) : null}
                        </label>
                        <label style={fieldStyle}>
                          <span style={fieldLabelStyle}>上架量上限</span>
                          <input
                            value={subscriptionForm.maxListings}
                            onChange={(event) => setSubscriptionField("maxListings", event.target.value)}
                            placeholder="1000"
                            aria-invalid={Boolean(subscriptionErrors.maxListings)}
                            style={getInputFieldStyle(Boolean(subscriptionErrors.maxListings))}
                          />
                          {subscriptionErrors.maxListings ? (
                            <span style={fieldErrorTextStyle}>{subscriptionErrors.maxListings}</span>
                          ) : null}
                        </label>
                      </div>
                      <label style={fieldStyle}>
                        <span style={fieldLabelStyle}>操作原因</span>
                        <textarea
                          rows={4}
                          value={subscriptionForm.reason}
                          onChange={(event) => setSubscriptionField("reason", event.target.value)}
                          placeholder="说明为什么调整订阅"
                          aria-invalid={Boolean(subscriptionErrors.reason)}
                          style={getTextAreaFieldStyle(Boolean(subscriptionErrors.reason))}
                        />
                        {subscriptionErrors.reason ? <span style={fieldErrorTextStyle}>{subscriptionErrors.reason}</span> : null}
                      </label>
                      <div style={dialogFooterStyle}>
                        <button type="button" style={primaryButtonStyle} onClick={() => void submitSubscriptionUpdate()} disabled={isMutating}>
                          {isMutating ? "保存中..." : "更新订阅"}
                        </button>
                      </div>
                    </section>
                  </>
                ) : (
                  <div style={emptyStateStyle}>选择租户后查看用量并调整订阅。</div>
                )}
              </div>
            </div>
          </section>
        </section>

        <section style={sideRailStyle}>
          <section style={subPanelStyle}>
            <div style={subSectionTitleStyle}>系统概览</div>
            <div style={gridStyle}>
              <MetricCard label="状态" value={health?.status ?? "--"} />
              <MetricCard label="任务" value={String(health?.active_task_count ?? 0)} />
              <MetricCard label="审计" value={String(health?.audit_log_count ?? 0)} />
            </div>
            {dbHealth ? (
              <div style={inlineNoteStyle}>
                <strong>DB</strong>
                <span>{dbHealth.status}</span>
                <span style={mutedTextStyle}>{dbHealth.detail}</span>
              </div>
            ) : null}
          </section>

          <section style={subPanelStyle}>
            <div style={subSectionTitleStyle}>订阅护栏</div>
            <div style={inlineNoteStyle}>
              <strong>{tenantUsage?.plan_name ?? "--"}</strong>
              <span style={mutedTextStyle}>{formatSubscriptionStatus(tenantUsage?.subscription_status)}</span>
              <span style={mutedTextStyle}>试用到期：{formatDateTime(tenantUsage?.trial_ends_at)}</span>
              <span style={mutedTextStyle}>付费有效期：{formatDateTime(tenantUsage?.current_period_ends_at)}</span>
            </div>
            <div style={gridStyle}>
              <MetricCard label="用户" value={formatQuota(tenantUsage?.usage.active_users, tenantUsage?.limits.max_users)} />
              <MetricCard label="店铺" value={formatQuota(tenantUsage?.usage.active_stores, tenantUsage?.limits.max_stores)} />
              <MetricCard
                label="同步任务"
                value={formatQuota(tenantUsage?.usage.active_sync_tasks, tenantUsage?.limits.max_active_sync_tasks)}
              />
              <MetricCard label="上架量" value={formatQuota(tenantUsage?.usage.listings, tenantUsage?.limits.max_listings)} />
            </div>
            {(tenantUsage?.warnings ?? []).map((warning) => (
              <div key={warning} style={warningStyle}>
                {warning}
              </div>
            ))}
          </section>

          <section style={subPanelStyle}>
            <div style={subSectionTitleStyle}>审计摘要</div>
            <div style={{ display: "grid", gap: 10 }}>
              {audits.slice(0, 6).map((audit) => (
                <div key={audit.audit_id} style={auditRowStyle}>
                  <strong>{audit.action_label}</strong>
                  <span style={mutedTextStyle}>
                    {audit.actor_display_name ?? audit.actor_user_id ?? "system"} / {audit.result}
                  </span>
                  <span style={mutedTextStyle}>
                    {audit.target_label ?? audit.target_id ?? "--"}
                  </span>
                </div>
              ))}
            </div>
          </section>

          <section style={subPanelStyle}>
            <div style={subSectionTitleStyle}>发布开关</div>
            <div style={{ display: "grid", gap: 10 }}>
              {(health?.release_switches ?? []).slice(0, 6).map((setting) => (
                <div key={setting.setting_key} style={auditRowStyle}>
                  <strong>{setting.setting_key}</strong>
                  <span style={mutedTextStyle}>{String(setting.value)}</span>
                </div>
              ))}
            </div>
          </section>
        </section>
      </div>

      <DangerousActionDialog
        open={dialogState.open}
        title={dialogState.title}
        riskText={dialogState.riskText}
        confirmLabel={dialogState.confirmLabel}
        reason={dialogReason}
        isSubmitting={isMutating}
        onReasonChange={setDialogReason}
        onConfirm={() => void confirmAction()}
        onCancel={closeActionDialog}
      />

      <AdminFormDialog
        open={createUserOpen}
        eyebrow="管理账号"
        title="新建控制台用户"
        description="创建新的控制台账号。临时密码仅用于交接，交接后应立即轮换。"
        onClose={() => {
          if (!isMutating) closeCreateUserDialog();
        }}
        footer={
          <>
            <button type="button" style={buttonStyle} onClick={closeCreateUserDialog} disabled={isMutating}>
              取消
            </button>
            <button
              type="button"
              style={primaryButtonStyle}
              data-testid="create-user-submit"
              onClick={() => void submitCreateUser()}
              disabled={isMutating}
            >
              {isMutating ? "创建中..." : "创建用户"}
            </button>
          </>
        }
      >
        <label style={fieldStyle}>
          <span style={fieldLabelStyle}>用户名</span>
          <input
            value={createUserForm.username}
            onChange={(event) => setCreateUserField("username", event.target.value)}
            placeholder="new-operator"
            data-testid="create-user-username"
            aria-invalid={Boolean(createUserErrors.username)}
            style={getInputFieldStyle(Boolean(createUserErrors.username))}
          />
          {createUserErrors.username ? <span style={fieldErrorTextStyle}>{createUserErrors.username}</span> : null}
        </label>

        <label style={fieldStyle}>
          <span style={fieldLabelStyle}>邮箱</span>
          <input
            value={createUserForm.email}
            onChange={(event) => setCreateUserField("email", event.target.value)}
            placeholder="owner@example.com"
            data-testid="create-user-email"
            aria-invalid={Boolean(createUserErrors.email)}
            style={getInputFieldStyle(Boolean(createUserErrors.email))}
          />
          {createUserErrors.email ? <span style={fieldErrorTextStyle}>{createUserErrors.email}</span> : null}
        </label>

        <div style={dialogFormGridStyle}>
          <label style={fieldStyle}>
            <span style={fieldLabelStyle}>角色</span>
            <select
              value={createUserForm.role}
              onChange={(event) => setCreateUserField("role", event.target.value)}
              data-testid="create-user-role"
              style={inputStyle}
            >
              <option value="super_admin">超级管理员</option>
              <option value="tenant_admin">租户管理员</option>
              <option value="operator">运营</option>
              <option value="warehouse">仓库</option>
            </select>
          </label>

          <label style={fieldStyle}>
            <span style={fieldLabelStyle}>临时密码</span>
            <input
              value={createUserForm.password}
              onChange={(event) => setCreateUserField("password", event.target.value)}
              placeholder="temp12345"
              data-testid="create-user-password"
              aria-invalid={Boolean(createUserErrors.password)}
              style={getInputFieldStyle(Boolean(createUserErrors.password))}
            />
            {createUserErrors.password ? <span style={fieldErrorTextStyle}>{createUserErrors.password}</span> : null}
          </label>
        </div>
      </AdminFormDialog>

      <AdminFormDialog
        open={expiryDialog.open}
        eyebrow="访问窗口"
        title={`设置到期 / ${selectedUser?.username ?? "--"}`}
        description="时间为空时表示清除到期时间，并恢复不限期访问。"
        onClose={() => {
          if (!isMutating) closeExpiryDialog();
        }}
        footer={
          <>
            <button type="button" style={buttonStyle} onClick={closeExpiryDialog} disabled={isMutating}>
              取消
            </button>
            <button
              type="button"
              style={primaryButtonStyle}
              data-testid="expiry-submit"
              onClick={() => void submitExpiry()}
              disabled={isMutating}
            >
              {isMutating ? "保存中..." : "保存到期时间"}
            </button>
          </>
        }
      >
        <label style={fieldStyle}>
          <span style={fieldLabelStyle}>到期时间</span>
          <input
            type="datetime-local"
            step="1"
            value={expiryDialog.expiresAt}
            onChange={(event) => setExpiryField("expiresAt", event.target.value)}
            data-testid="expiry-input"
            aria-invalid={Boolean(expiryErrors.expiresAt)}
            style={getInputFieldStyle(Boolean(expiryErrors.expiresAt))}
          />
          {expiryErrors.expiresAt ? <span style={fieldErrorTextStyle}>{expiryErrors.expiresAt}</span> : null}
        </label>

        <label style={fieldStyle}>
          <span style={fieldLabelStyle}>操作原因</span>
          <textarea
            rows={4}
            value={expiryDialog.reason}
            onChange={(event) => setExpiryField("reason", event.target.value)}
            placeholder="说明为什么调整访问窗口"
            data-testid="expiry-reason"
            aria-invalid={Boolean(expiryErrors.reason)}
            style={getTextAreaFieldStyle(Boolean(expiryErrors.reason))}
          />
          {expiryErrors.reason ? <span style={fieldErrorTextStyle}>{expiryErrors.reason}</span> : null}
        </label>
      </AdminFormDialog>
    </>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div style={metricCardStyle}>
      <div style={metricLabelStyle}>{label}</div>
      <div style={metricValueStyle}>{value}</div>
    </div>
  );
}

function Property({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "grid", gap: 4 }}>
      <span style={metricLabelStyle}>{label}</span>
      <span>{value}</span>
    </div>
  );
}

function AdminFormDialog({
  open,
  eyebrow,
  title,
  description,
  onClose,
  footer,
  children,
}: {
  open: boolean;
  eyebrow: string;
  title: string;
  description: string;
  onClose: () => void;
  footer: ReactNode;
  children: ReactNode;
}) {
  if (!open) return null;

  return (
    <div style={dialogBackdropStyle}>
      <div style={dialogPanelStyle}>
        <div style={sectionHeaderStyle}>
          <div style={{ display: "grid", gap: 6 }}>
            <div style={eyebrowStyle}>{eyebrow}</div>
            <div style={dialogTitleStyle}>{title}</div>
          </div>
          <button type="button" style={buttonStyle} onClick={onClose}>
            Close
          </button>
        </div>

        <div style={dialogDescriptionStyle}>{description}</div>
        <div style={{ display: "grid", gap: 14 }}>{children}</div>
        <div style={dialogFooterStyle}>{footer}</div>
      </div>
    </div>
  );
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function toDateTimeInputValue(value: string | null | undefined) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const timezoneOffsetMs = date.getTimezoneOffset() * 60 * 1000;
  return new Date(date.getTime() - timezoneOffsetMs).toISOString().slice(0, 19);
}

function validateCreateUserForm(form: CreateUserFormState): CreateUserFormErrors {
  const errors: CreateUserFormErrors = {};
  const normalizedUsername = form.username.trim();
  const normalizedEmail = form.email.trim();

  if (!normalizedUsername) {
    errors.username = "请输入用户名。";
  } else if (normalizedUsername.length < 3 || normalizedUsername.length > 32) {
    errors.username = "请使用 3-32 个字符。";
  } else if (!/^[A-Za-z0-9_-]+$/.test(normalizedUsername)) {
    errors.username = "仅支持字母、数字、`_` 或 `-`。";
  }

  if (normalizedEmail && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalizedEmail)) {
    errors.email = "请输入有效邮箱。";
  }

  if (!form.password.trim()) {
    errors.password = "请输入临时密码。";
  } else if (form.password.trim().length < 8) {
    errors.password = "至少 8 个字符。";
  }

  return errors;
}

function validateExpiryDialog(dialog: ExpiryDialogState): ExpiryDialogErrors {
  const errors: ExpiryDialogErrors = {};

  if (dialog.expiresAt) {
    const nextExpiry = new Date(dialog.expiresAt);
    if (Number.isNaN(nextExpiry.getTime())) {
      errors.expiresAt = "请选择有效日期和时间。";
    } else if (nextExpiry.getTime() <= Date.now()) {
      errors.expiresAt = "到期时间必须晚于当前时间。";
    }
  }

  if (!dialog.reason.trim()) {
    errors.reason = "请说明为什么调整访问窗口。";
  }

  return errors;
}

function validateCreateTenantForm(form: CreateTenantFormState): CreateTenantFormErrors {
  const errors: CreateTenantFormErrors = {};
  const normalizedName = form.name.trim();
  const normalizedSlug = form.slug.trim();
  const normalizedPlan = form.plan.trim();
  const normalizedAdminUsername = form.adminUsername.trim();
  const normalizedAdminEmail = form.adminEmail.trim();
  const normalizedAdminPassword = form.adminPassword.trim();

  if (!normalizedName) {
    errors.name = "请输入租户名称。";
  }

  if (!normalizedSlug) {
    errors.slug = "请输入租户标识。";
  } else if (!/^[a-z0-9](?:[a-z0-9-]{1,62}[a-z0-9])$/.test(normalizedSlug)) {
    errors.slug = "请使用 3-64 位小写字母、数字或中间 `-`。";
  }

  if (!["starter", "growth", "scale", "war-room"].includes(normalizedPlan)) {
    errors.plan = "请使用 starter、growth、scale 或 war-room。";
  }

  if (!normalizedAdminUsername) {
    errors.adminUsername = "请输入首个管理员账号。";
  } else if (!/^[A-Za-z0-9_-]{3,32}$/.test(normalizedAdminUsername)) {
    errors.adminUsername = "请使用 3-32 位字母、数字、`_` 或 `-`。";
  }

  if (normalizedAdminEmail && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalizedAdminEmail)) {
    errors.adminEmail = "请输入有效管理员邮箱。";
  }

  if (!normalizedAdminPassword) {
    errors.adminPassword = "请输入初始密码。";
  } else if (normalizedAdminPassword.length < 8) {
    errors.adminPassword = "至少 8 个字符。";
  }

  if (!form.reason.trim()) {
    errors.reason = "请说明为什么创建该租户。";
  }

  return errors;
}

function validateSubscriptionForm(form: SubscriptionFormState): SubscriptionFormErrors {
  const errors: SubscriptionFormErrors = {};

  if (!form.planName.trim()) {
    errors.planName = "请输入套餐名称。";
  }

  if (!form.subscriptionStatus.trim()) {
    errors.subscriptionStatus = "请选择订阅状态。";
  }

  for (const [key, value] of Object.entries({
    maxUsers: form.maxUsers,
    maxStores: form.maxStores,
    maxActiveSyncTasks: form.maxActiveSyncTasks,
    maxListings: form.maxListings,
  })) {
    if (value.trim() && !/^\d+$/.test(value.trim())) {
      errors[key as keyof SubscriptionFormErrors] = "请输入非负整数。";
    }
  }

  for (const [key, value] of Object.entries({
    trialEndsAt: form.trialEndsAt,
    currentPeriodEndsAt: form.currentPeriodEndsAt,
  })) {
    if (value.trim() && Number.isNaN(new Date(value).getTime())) {
      errors[key as keyof SubscriptionFormErrors] = "请选择有效日期和时间。";
    }
  }

  if (form.subscriptionStatus === "trialing" && !form.trialEndsAt.trim()) {
    errors.trialEndsAt = "试用租户必须设置试用到期时间。";
  }

  if (form.subscriptionStatus === "active" && !form.currentPeriodEndsAt.trim()) {
    errors.currentPeriodEndsAt = "正常订阅必须设置付费有效期。";
  }

  if (!form.reason.trim()) {
    errors.reason = "请说明为什么调整订阅。";
  }

  return errors;
}

function hasValidationErrors(errors: Record<string, string | undefined>) {
  return Object.values(errors).some(Boolean);
}

function parseNullableInteger(value: string) {
  const normalized = value.trim();
  if (!normalized) return null;
  return Number.parseInt(normalized, 10);
}

function toNullableNumberInput(value: number | null | undefined) {
  if (value === null || value === undefined) return "";
  return String(value);
}

function formatQuota(used: number | null | undefined, limit: number | null | undefined) {
  if (used === null || used === undefined || limit === null || limit === undefined) return "--";
  return `${used}/${limit}`;
}

function formatUsageSummary(
  usageData: TenantUsageResponse | AdminTenantUsageResponse | null | undefined,
) {
  if (!usageData) return "--";

  return [
    `users ${formatQuota(usageData.usage.active_users, usageData.limits.max_users)}`,
    `stores ${formatQuota(usageData.usage.active_stores, usageData.limits.max_stores)}`,
    `sync ${formatQuota(usageData.usage.active_sync_tasks, usageData.limits.max_active_sync_tasks)}`,
    `listings ${formatQuota(usageData.usage.listings, usageData.limits.max_listings)}`,
  ].join(" · ");
}

function formatRemaining(used: number | null | undefined, limit: number | null | undefined) {
  if (used === null || used === undefined || limit === null || limit === undefined) return "--";
  return String(Math.max(limit - used, 0));
}

function formatRemainingSummary(
  usageData: TenantUsageResponse | AdminTenantUsageResponse | null | undefined,
) {
  if (!usageData) return "--";

  return [
    `users ${formatRemaining(usageData.usage.active_users, usageData.limits.max_users)}`,
    `stores ${formatRemaining(usageData.usage.active_stores, usageData.limits.max_stores)}`,
    `sync ${formatRemaining(usageData.usage.active_sync_tasks, usageData.limits.max_active_sync_tasks)}`,
    `listings ${formatRemaining(usageData.usage.listings, usageData.limits.max_listings)}`,
  ].join(" · ");
}

function resolveUserStatus(
  status: string | null | undefined,
  expiresAt: string | null | undefined,
  nowMs: number,
) {
  if (!status) return null;
  if (status !== "active") return status;
  if (!expiresAt) return status;
  const expiresAtMs = new Date(expiresAt).getTime();
  if (Number.isNaN(expiresAtMs)) return status;
  return expiresAtMs <= nowMs ? "expired" : status;
}

function getStatusLabel(status: string | null | undefined) {
  switch (status) {
    case "active":
      return "正常";
    case "expired":
      return "已过期";
    case "disabled":
      return "已停用";
    case "pending":
      return "待处理";
    case "locked":
      return "已锁定";
    case "suspended":
      return "已暂停";
    default:
      return status ?? "--";
  }
}

function formatRole(role: string | null | undefined) {
  switch (role) {
    case "super_admin":
      return "超级管理员";
    case "tenant_admin":
      return "租户管理员";
    case "operator":
      return "运营";
    case "warehouse":
      return "仓库";
    default:
      return role ?? "--";
  }
}

function formatSubscriptionStatus(status: string | null | undefined) {
  switch (status) {
    case "active":
      return "正常";
    case "trialing":
      return "试用中";
    case "past_due":
      return "逾期";
    case "paused":
      return "已暂停";
    case "cancelled":
      return "已取消";
    default:
      return status ?? "--";
  }
}

function statusPillStyle(status: string) {
  return {
    ...pillStyleBase,
    background: "#FFFFFF",
    border: "1px solid #EBEBEB",
    color: ["disabled", "expired", "locked", "suspended"].includes(status) ? "#D9363E" : "#000000",
  } satisfies React.CSSProperties;
}

function flagPillStyle(enabled: boolean) {
  return {
    ...pillStyleBase,
    background: "#FFFFFF",
    border: "1px solid #EBEBEB",
    color: enabled ? "#000000" : "#595959",
  } satisfies React.CSSProperties;
}

const pageStyle = {
  display: "grid",
  gap: 16,
  gridTemplateColumns: "320px minmax(0, 1fr) 320px",
  alignItems: "start",
} satisfies React.CSSProperties;

const panelStyle = {
  background: "#ffffff",
  border: "1px solid #EBEBEB",
  borderRadius: 6,
  padding: 20,
  boxShadow: "none",
} satisfies React.CSSProperties;

const sidebarStyle = {
  ...panelStyle,
  display: "grid",
  gap: 16,
  position: "sticky" as const,
  top: 24,
} satisfies React.CSSProperties;

const detailStyle = {
  ...panelStyle,
  display: "grid",
  gap: 16,
} satisfies React.CSSProperties;

const sideRailStyle = {
  display: "grid",
  gap: 16,
} satisfies React.CSSProperties;

const subPanelStyle = {
  border: "1px solid #EBEBEB",
  borderRadius: 6,
  padding: 16,
  display: "grid",
  gap: 14,
} satisfies React.CSSProperties;

const sectionHeaderStyle = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "flex-start",
  gap: 12,
} satisfies React.CSSProperties;

const eyebrowStyle = {
  fontSize: 12,
  fontWeight: 700,
  color: "#595959",
  textTransform: "uppercase" as const,
  letterSpacing: "0.08em",
} satisfies React.CSSProperties;

const sectionTitleStyle = {
  fontSize: 24,
  fontWeight: 700,
} satisfies React.CSSProperties;

const subSectionTitleStyle = {
  fontSize: 16,
  fontWeight: 700,
} satisfies React.CSSProperties;

const mutedTextStyle = {
  color: "#595959",
  fontSize: 13,
} satisfies React.CSSProperties;

const inputStyle = {
  border: "1px solid #EBEBEB",
  borderRadius: 6,
  padding: "10px 12px",
  fontSize: 14,
  width: "100%",
  color: "#000000",
  background: "#FFFFFF",
} satisfies React.CSSProperties;

const textAreaStyle = {
  ...inputStyle,
  resize: "vertical" as const,
  minHeight: 120,
} satisfies React.CSSProperties;

function getInputFieldStyle(hasError: boolean) {
  return hasError
    ? {
        ...inputStyle,
        borderColor: "#D9363E",
        boxShadow: "none",
      }
    : inputStyle;
}

function getTextAreaFieldStyle(hasError: boolean) {
  return hasError
    ? {
        ...textAreaStyle,
        borderColor: "#D9363E",
        boxShadow: "none",
      }
    : textAreaStyle;
}

const userCardStyle = {
  border: "1px solid #EBEBEB",
  borderRadius: 6,
  padding: 14,
  background: "#ffffff",
  display: "grid",
  gap: 10,
  textAlign: "left" as const,
  cursor: "pointer",
} satisfies React.CSSProperties;

const gridStyle = {
  display: "grid",
  gap: 12,
  gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
} satisfies React.CSSProperties;

const propertyGridStyle = {
  display: "grid",
  gap: 12,
  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
} satisfies React.CSSProperties;

const tenantWorkspaceStyle = {
  display: "grid",
  gap: 16,
  gridTemplateColumns: "280px minmax(0, 1fr)",
  alignItems: "start",
} satisfies React.CSSProperties;

const featureFlagRowStyle = {
  border: "1px solid #EBEBEB",
  borderRadius: 6,
  padding: "12px 14px",
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  gap: 12,
} satisfies React.CSSProperties;

const actionGridStyle = {
  display: "flex",
  flexWrap: "wrap" as const,
  gap: 10,
} satisfies React.CSSProperties;

const tenantActionRowStyle = {
  display: "flex",
  flexWrap: "wrap" as const,
  gap: 10,
  alignItems: "center",
} satisfies React.CSSProperties;

const buttonStyle = {
  border: "1px solid #EBEBEB",
  borderRadius: 6,
  padding: "9px 12px",
  background: "#ffffff",
  color: "#000000",
  cursor: "pointer",
  fontSize: 13,
  fontWeight: 600,
} satisfies React.CSSProperties;

const primaryButtonStyle = {
  ...buttonStyle,
  border: "1px solid #000000",
  background: "#000000",
  color: "#ffffff",
  boxShadow: "none",
} satisfies React.CSSProperties;

const pillRowStyle = {
  display: "flex",
  flexWrap: "wrap" as const,
  gap: 6,
} satisfies React.CSSProperties;

const pillStyleBase = {
  borderRadius: 6,
  padding: "4px 8px",
  fontSize: 12,
  fontWeight: 700,
} satisfies React.CSSProperties;

const metricCardStyle = {
  border: "1px solid #EBEBEB",
  borderRadius: 6,
  padding: 14,
  display: "grid",
  gap: 4,
} satisfies React.CSSProperties;

const metricLabelStyle = {
  color: "#595959",
  fontSize: 12,
  fontWeight: 600,
} satisfies React.CSSProperties;

const metricValueStyle = {
  fontSize: 20,
  fontWeight: 700,
} satisfies React.CSSProperties;

const inlineNoteStyle = {
  borderRadius: 6,
  background: "#FAFAFA",
  border: "1px solid #EBEBEB",
  padding: "12px 14px",
  display: "grid",
  gap: 4,
} satisfies React.CSSProperties;

const auditRowStyle = {
  border: "1px solid #EBEBEB",
  borderRadius: 6,
  padding: "12px 14px",
  display: "grid",
  gap: 4,
} satisfies React.CSSProperties;

const emptyStateStyle = {
  borderRadius: 6,
  border: "1px dashed #EBEBEB",
  color: "#595959",
  padding: 24,
  textAlign: "center" as const,
} satisfies React.CSSProperties;

const errorStyle = {
  borderRadius: 6,
  border: "1px solid #EBEBEB",
  background: "#FFFFFF",
  color: "#D9363E",
  padding: "12px 14px",
  fontSize: 14,
} satisfies React.CSSProperties;

const successStyle = {
  borderRadius: 6,
  border: "1px solid #EBEBEB",
  background: "#FFFFFF",
  color: "#000000",
  padding: "12px 14px",
  fontSize: 14,
} satisfies React.CSSProperties;

const warningStyle = {
  borderRadius: 6,
  border: "1px solid #EBEBEB",
  background: "#FFFFFF",
  color: "#D9363E",
  padding: "10px 12px",
  fontSize: 12,
  fontWeight: 700,
} satisfies React.CSSProperties;

const dialogBackdropStyle = {
  position: "fixed",
  inset: 0,
  background: "rgba(0, 0, 0, 0.32)",
  display: "grid",
  placeItems: "center",
  padding: 24,
  zIndex: 40,
} satisfies React.CSSProperties;

const dialogPanelStyle = {
  width: "min(680px, 100%)",
  background: "#ffffff",
  border: "1px solid #EBEBEB",
  borderRadius: 6,
  padding: 20,
  display: "grid",
  gap: 18,
  boxShadow: "none",
} satisfies React.CSSProperties;

const dialogTitleStyle = {
  fontSize: 28,
  fontWeight: 700,
} satisfies React.CSSProperties;

const dialogDescriptionStyle = {
  color: "#595959",
  fontSize: 14,
  lineHeight: 1.6,
} satisfies React.CSSProperties;

const dialogFooterStyle = {
  display: "flex",
  justifyContent: "flex-end",
  gap: 10,
  flexWrap: "wrap" as const,
} satisfies React.CSSProperties;

const dialogFormGridStyle = {
  display: "grid",
  gap: 12,
  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
} satisfies React.CSSProperties;

const fieldStyle = {
  display: "grid",
  gap: 8,
} satisfies React.CSSProperties;

const fieldLabelStyle = {
  fontSize: 13,
  fontWeight: 700,
  color: "#000000",
} satisfies React.CSSProperties;

const fieldErrorTextStyle = {
  color: "#D9363E",
  fontSize: 12,
  lineHeight: 1.4,
  letterSpacing: "0.01em",
} satisfies React.CSSProperties;
