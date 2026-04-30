import { ActivationPanel } from "@/components/subscription/ActivationPanel";
import { getServerSessionInfo } from "@/lib/server-session";

export default async function ActivatePage() {
  const session = await getServerSessionInfo();
  return (
    <ActivationPanel
      username={session?.user.username ?? "--"}
      subscriptionStatus={session?.subscription_status ?? "unactivated"}
    />
  );
}
