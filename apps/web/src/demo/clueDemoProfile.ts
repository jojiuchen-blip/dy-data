export const CLUE_DEMO_PROFILE = {
  seed: 20260717,
  leadCount: 480,
  storeCount: 48,
  cityCount: 12,
  oneRoundLeadCount: 230,
  twoRoundLeadCount: 90,
  threeRoundLeadCount: 40,
  directHeadquartersLeadCount: 60,
  terminalWithoutRoundLeadCount: 60,
  minimumFollowUpCount: 650,
  maximumFollowUpCount: 750,
} as const;

export const DEMO_REGIONS = [
  { province: "广东", city: "深圳", cityCode: "440300", weight: 16, latitude: 22.5431, longitude: 114.0579 },
  { province: "广东", city: "广州", cityCode: "440100", weight: 12, latitude: 23.1291, longitude: 113.2644 },
  { province: "河南", city: "郑州", cityCode: "410100", weight: 11, latitude: 34.7466, longitude: 113.6254 },
  { province: "陕西", city: "西安", cityCode: "610100", weight: 10, latitude: 34.3416, longitude: 108.9398 },
  { province: "安徽", city: "合肥", cityCode: "340100", weight: 9, latitude: 31.8206, longitude: 117.2272 },
  { province: "湖北", city: "武汉", cityCode: "420100", weight: 9, latitude: 30.5928, longitude: 114.3055 },
  { province: "江苏", city: "苏州", cityCode: "320500", weight: 8, latitude: 31.2989, longitude: 120.5853 },
  { province: "浙江", city: "杭州", cityCode: "330100", weight: 8, latitude: 30.2741, longitude: 120.1551 },
  { province: "山东", city: "济南", cityCode: "370100", weight: 6, latitude: 36.6512, longitude: 117.1201 },
  { province: "河北", city: "石家庄", cityCode: "130100", weight: 5, latitude: 38.0428, longitude: 114.5149 },
  { province: "四川", city: "成都", cityCode: "510100", weight: 4, latitude: 30.5728, longitude: 104.0668 },
  { province: "福建", city: "福州", cityCode: "350100", weight: 2, latitude: 26.0745, longitude: 119.2965 },
] as const;

export const DEMO_PRODUCTS = [
  { productId: "DEMO-PRODUCT-MAINT-01", name: "基础保养演示套餐", type: "保养服务" },
  { productId: "DEMO-PRODUCT-MAINT-02", name: "四轮定位演示服务", type: "保养服务" },
  { productId: "DEMO-PRODUCT-WASH-01", name: "精洗护理演示套餐", type: "洗美服务" },
  { productId: "DEMO-PRODUCT-TIRE-01", name: "轮胎安装演示服务", type: "轮胎服务" },
] as const;

export const DEMO_FOLLOW_UP_NOTES = [
  "客户希望周末到店，已确认可联系时间。",
  "已介绍服务内容，客户需要再确认行程。",
  "首次拨打未接通，稍后继续联系。",
  "客户暂不需要本次服务。",
  "客户希望调整到更方便的门店。",
] as const;

export const DEMO_STORE_LABELS = ["中心", "东区", "南区", "高新"] as const;

export const DEMO_AUTHOR_LABELS = [
  "通勤车主",
  "周末养车",
  "保养咨询",
  "到店询价",
  "服务预约",
  "用车达人",
] as const;
