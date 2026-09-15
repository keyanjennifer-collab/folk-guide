import { DAILY_IDEAS, QUIZ, SCENT_QUIZ, matchScent } from "./discovery";
import { PRODUCTS, Product } from "../../data/products";
Page({
  data: {
    tab:"daily", tabs:[{id:"daily",label:"节气日常"},{id:"scent",label:"选香小测"},{id:"quiz",label:"国学一题"}],
    ideas:DAILY_IDEAS, expanded:-1, scentQuestions:SCENT_QUIZ, moment:"", note:"", result:null as Product|null,
    question:QUIZ[0], questionIndex:0, chosen:-1, revealed:false, total:QUIZ.length,
  },
  onLoad(options:Record<string,string>){if(this.data.tabs.some(t=>t.id===options.tab))this.setData({tab:options.tab});},
  switchSection(e:WechatMiniprogram.TouchEvent){const tab=e.currentTarget.dataset.id;if(this.data.tabs.some(t=>t.id===tab))this.setData({tab});},
  toggleIdea(e:WechatMiniprogram.TouchEvent){const i=Number(e.currentTarget.dataset.index);if(i>=0&&i<DAILY_IDEAS.length)this.setData({expanded:this.data.expanded===i?-1:i});},
  chooseTaste(e:WechatMiniprogram.TouchEvent){
    const step=Number(e.currentTarget.dataset.step), id=String(e.currentTarget.dataset.id);
    if(!SCENT_QUIZ[step]?.options.some(o=>o.id===id))return;
    const moment=step===0?id:this.data.moment, note=step===1?id:this.data.note;
    const result=PRODUCTS.find(p=>p.id===matchScent(moment,note))||null;
    this.setData({moment,note,result});
  },
  resetTaste(){this.setData({moment:"",note:"",result:null});},
  toProduct(){if(this.data.result)wx.navigateTo({url:"/pages/product/index?id="+this.data.result.id});},
  chooseAnswer(e:WechatMiniprogram.TouchEvent){
    const chosen=Number(e.currentTarget.dataset.index);
    if(this.data.revealed||!Number.isInteger(chosen)||!this.data.question.options[chosen])return;
    this.setData({chosen,revealed:true});
  },
  nextQuestion(){const questionIndex=(this.data.questionIndex+1)%QUIZ.length;this.setData({questionIndex,question:QUIZ[questionIndex],chosen:-1,revealed:false});},
  copySource(){wx.setClipboardData({data:this.data.question.source});},
});
