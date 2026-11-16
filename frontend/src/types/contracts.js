/** @typedef {{id:number,hour:string,pressure:number,flow:number,temperature:number,machines:number,sensor_noise:number,kwh:number,note:string}} Sample */
/** @typedef {{id:number,name:string,features:string[],alphas:number[],state:string,result:object,error:string}} Run */
/** @typedef {{id:number,run_id:number,title:string,finding:string,action:string,status:string}} Review */
/** @typedef {{hour:string,workshop:string,demand:number,pressure:number,temperature:number,available_machines:number}} DemandRow */
/** @typedef {{capacity_per_machine:number,startup_kwh:number,initial_machines:number,max_starts:number}} PlanParams */
/** @typedef {{id:number,name:string,state:string,kind:string,model_run_id:number,parent_plan_id:number|null,params:PlanParams,input:{hours:object[]},result:object,checksum:string,conflicts:number[],occupied_hours:string[]}} Plan */
/** @typedef {{hour:string,demand:number,workshops:{workshop:string,demand:number}[],pressure:number,temperature:number,available_machines:number,required_machines:number,machines:number,started:number,load_ratio:number,operation_kwh:number,startup_kwh:number,total_kwh:number}} PlanHour */
