export const routes=['耗电样本','特征方案','模型比选','排机计划','节能评议'];export const page=()=>Math.min(routes.length-1,Math.max(0,Number(location.hash.slice(1)||0)));
