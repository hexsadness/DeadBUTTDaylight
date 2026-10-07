"""DBD Haptics: external screen detector + Intiface/Buttplug output."""
import asyncio, os, queue, re, threading, time
from difflib import SequenceMatcher
import cv2, mss, numpy as np, pytesseract
from buttplug import ButtplugClient, DeviceOutputCommand, OutputType

MONITOR_NUMBER = 2
TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
WINDOW_NAME = "DBD Haptics"
INTIFACE_ADDRESS = "ws://127.0.0.1:12345"
DEVICE_SCAN_TIME = 10.0

ACTION_STRENGTHS = {"REPAIR":.30,"HEAL":.30,"RECOVER":.25,"WIGGLE":.45,"STRUGGLE":.45,"SABOTAGE":.35,"SEARCH":.20,"CLEANSE":.30,"UNHOOK":.35,"HOOK":.35,"OPEN":.30,"VAULT":.25,"HIDE":.20,"MEND":.30,"PICKUP":.30,"BREAK":.35,"BLESS":.30,"REKINDLE":.30,"SNAP":.30,"ESCAPE":.40}
DEFAULT_ACTION_STRENGTH=.25
HEARTBEAT_STRENGTH=.20
INJURY_STRENGTH=.80
INJURY_PULSE_DURATION=.40

regions={
 "health":{"x":50,"y":380,"width":300,"height":420},
 "heartbeat":{"x":605,"y":400,"width":695,"height":600},
 "action_bar":{"x":800,"y":815,"width":340,"height":180},
}

HEARTBEAT_MIN_VALUE=242; HEARTBEAT_MIN_SATURATION=120; HEARTBEAT_MIN_PIXELS=5
HEARTBEAT_RED_LOW_1=0; HEARTBEAT_RED_HIGH_1=13; HEARTBEAT_RED_LOW_2=167; HEARTBEAT_RED_HIGH_2=179
HEARTBEAT_TIMEOUT=1.8; HEARTBEAT_RESET_TIME=.10
HEALTH_RED_MIN_VALUE=175; HEALTH_RED_MIN_SATURATION=120; HEALTH_FLASH_ABSOLUTE_THRESHOLD=1500
HEALTH_FLASH_INCREASE_THRESHOLD=450; HEALTH_FLASH_COOLDOWN=1.0; HEALTH_BASELINE_ALPHA=.025
OCR_INTERVAL=.05; ACTION_CONFIRMATIONS=1; ACTION_LOST_CONFIRMATIONS=2; ACTION_MATCH_THRESHOLD=.58
ACTION_UI_LOST_FRAMES=4; ACTION_UI_GRACE_TIME=.30; ACTION_UI_MIN_SCORE=.018
ACTION_TEXT_X1=0; ACTION_TEXT_Y1=0; ACTION_TEXT_X2=200; ACTION_TEXT_Y2=80
ACTION_UI_X1=0; ACTION_UI_Y1=0; ACTION_UI_X2=340; ACTION_UI_Y2=110
ACTION_WORDS=["REPAIR","HEAL","RECOVER","WIGGLE","STRUGGLE","SABOTAGE","SEARCH","CLEANSE","UNHOOK","HOOK","OPEN","VAULT","HIDE","MEND","PICKUP","BREAK","BLESS","REKINDLE","SNAP","ESCAPE"]
ACTION_PHRASES={"CLEANSE TOTEM":"CLEANSE","BLESS TOTEM":"BLESS","OPEN GATE":"OPEN","OPEN CHEST":"OPEN","REPAIR GENERATOR":"REPAIR","REPAIR":"REPAIR","HEAL":"HEAL","RECOVER":"RECOVER","WIGGLE":"WIGGLE","STRUGGLE":"STRUGGLE","SABOTAGE":"SABOTAGE","SEARCH":"SEARCH","UNHOOK":"UNHOOK","MEND":"MEND"}

ocr_lock=threading.Lock(); latest_action_frame=None
ocr_result={"scan_id":0,"action":None,"text":"","score":0.0,"preview":None,"running":True}
device_event_queue=queue.Queue(); device_status_lock=threading.Lock()
device_status={"connected":False,"device_count":0,"action_strength":0.0,"heartbeat_active":False,"output_strength":0.0,"last_event":"NONE","error":""}

def send_device_event(kind,value=None): device_event_queue.put_nowait((kind,value))
def get_region_image(sct,monitor,r):
 area={"left":monitor["left"]+r["x"],"top":monitor["top"]+r["y"],"width":r["width"],"height":r["height"]}
 return cv2.cvtColor(np.array(sct.grab(area)),cv2.COLOR_BGRA2BGR)
def create_red_mask(frame,sat,val,l1,h1,l2,h2):
 hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
 return cv2.bitwise_or(cv2.inRange(hsv,np.array([l1,sat,val]),np.array([h1,255,255])),cv2.inRange(hsv,np.array([l2,sat,val]),np.array([h2,255,255])))
def detect_heartbeat(frame):
 mask=create_red_mask(frame,HEARTBEAT_MIN_SATURATION,HEARTBEAT_MIN_VALUE,HEARTBEAT_RED_LOW_1,HEARTBEAT_RED_HIGH_1,HEARTBEAT_RED_LOW_2,HEARTBEAT_RED_HIGH_2)
 mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((2,2),np.uint8)); n=cv2.countNonZero(mask)
 return n>=HEARTBEAT_MIN_PIXELS,n,mask
def detect_health_red(frame):
 mask=create_red_mask(frame,HEALTH_RED_MIN_SATURATION,HEALTH_RED_MIN_VALUE,0,15,165,179)
 return cv2.countNonZero(mask),mask
def preprocess_action(frame):
 crop=frame[ACTION_TEXT_Y1:ACTION_TEXT_Y2,ACTION_TEXT_X1:ACTION_TEXT_X2]
 gray=cv2.cvtColor(cv2.resize(crop,None,fx=3,fy=3,interpolation=cv2.INTER_CUBIC),cv2.COLOR_BGR2GRAY)
 _,bright=cv2.threshold(gray,170,255,cv2.THRESH_BINARY); k=np.ones((3,3),np.uint8)
 return cv2.morphologyEx(cv2.dilate(bright,k,iterations=1),cv2.MORPH_CLOSE,k)
def clean_ocr_text(text):
 text=text.upper().replace("0","O").replace("1","I").replace("|","I").replace("5","S")
 return re.sub(r"\s+"," ",re.sub(r"[^A-Z\s]"," ",text)).strip()
def find_action_from_text(text):
 text=clean_ocr_text(text)
 if not text:return None,0.0
 for phrase,action in ACTION_PHRASES.items():
  if phrase in text:return action,1.0
 words=text.split()
 for word in words:
  if word in ACTION_WORDS:return word,1.0
 best,bscore=None,0.0
 for word in words:
  if len(word)<3:continue
  for action in ACTION_WORDS:
   score=SequenceMatcher(None,word,action).ratio()
   if score>bscore:best,bscore=action,score
 return (best,bscore) if bscore>=ACTION_MATCH_THRESHOLD else (None,bscore)
def perform_ocr(frame):
 processed=preprocess_action(frame)
 config="--psm 11 -c preserve_interword_spaces=1 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ"
 try:
  text=clean_ocr_text(pytesseract.image_to_string(processed,config=config)); action,score=find_action_from_text(text)
  return action,text,score,processed
 except Exception as e:
  print("OCR ERROR:",e); return None,"",0.0,processed
def ocr_worker():
 global latest_action_frame
 while True:
  with ocr_lock:
   running=ocr_result["running"]; frame=None if latest_action_frame is None else latest_action_frame.copy()
  if not running:break
  if frame is None:time.sleep(.01);continue
  action,text,score,preview=perform_ocr(frame)
  with ocr_lock:
   ocr_result.update(scan_id=ocr_result["scan_id"]+1,action=action,text=text,score=score,preview=preview)
  time.sleep(OCR_INTERVAL)
def detect_action_ui(frame):
 crop=frame[ACTION_UI_Y1:ACTION_UI_Y2,ACTION_UI_X1:ACTION_UI_X2]; gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
 bright=cv2.inRange(gray,145,255); edges=cv2.Canny(gray,70,150)
 score=(cv2.countNonZero(bright)/float(bright.size))*.65+(cv2.countNonZero(edges)/float(edges.size))*.35
 return score>=ACTION_UI_MIN_SCORE,score,crop

async def set_all_devices(client,strength):
 strength=max(0.0,min(1.0,float(strength)))
 for device in client.devices.values():
  try:
   if device.has_output(OutputType.VIBRATE):
    if strength<=0: await device.stop()
    else: await device.run_output(DeviceOutputCommand(OutputType.VIBRATE,strength))
  except Exception as e: print("DEVICE OUTPUT ERROR:",device.name,e)
 with device_status_lock:device_status["output_strength"]=strength

async def buttplug_controller():
 client=ButtplugClient("DBD Haptics"); action_strength=0.0; heartbeat_on=False; temp_strength=0.0; temp_until=0.0
 try:
  print("Connecting to Intiface Central..."); await client.connect(INTIFACE_ADDRESS)
  with device_status_lock:device_status.update(connected=True,error="")
  print("Connected. Scanning for devices..."); await client.start_scanning(); await asyncio.sleep(DEVICE_SCAN_TIME); await client.stop_scanning()
  devices=list(client.devices.values())
  with device_status_lock:device_status["device_count"]=len(devices)
  for d in devices:print("DEVICE FOUND:",d.name,"| vibration:",d.has_output(OutputType.VIBRATE))
  last_output=-1.0
  while True:
   now=time.time()
   while True:
    try:kind,value=device_event_queue.get_nowait()
    except queue.Empty:break
    if kind=="SHUTDOWN":await set_all_devices(client,0);return
    if kind=="ACTION_START":action_strength=ACTION_STRENGTHS.get(value,DEFAULT_ACTION_STRENGTH)
    elif kind=="ACTION_END":action_strength=0.0
    elif kind=="HEARTBEAT_START":heartbeat_on=True
    elif kind=="HEARTBEAT_END":heartbeat_on=False
    elif kind=="INJURY":temp_strength=max(temp_strength,INJURY_STRENGTH);temp_until=max(temp_until,now+INJURY_PULSE_DURATION)
    with device_status_lock:
     device_status.update(action_strength=action_strength,heartbeat_active=heartbeat_on,last_event=f"{kind}: {value}" if value else kind)
    device_event_queue.task_done()
   continuous=max(action_strength,HEARTBEAT_STRENGTH if heartbeat_on else 0.0)
   if now<temp_until:desired=max(continuous,temp_strength)
   else:temp_strength=0.0;desired=continuous
   if abs(desired-last_output)>.001:await set_all_devices(client,desired);last_output=desired
   await asyncio.sleep(.01)
 except Exception as e:
  print("BUTTPLUG ERROR:",e)
  with device_status_lock:device_status.update(connected=False,error=str(e))
 finally:
  for d in client.devices.values():
   try:await d.stop()
   except Exception:pass
  try:await client.disconnect()
  except Exception:pass
  with device_status_lock:device_status.update(connected=False,output_strength=0.0,action_strength=0.0,heartbeat_active=False)
def buttplug_thread_worker(): asyncio.run(buttplug_controller())

def main():
 global latest_action_frame
 if not os.path.isfile(TESSERACT_PATH):print("Tesseract not found:",TESSERACT_PATH);return
 pytesseract.pytesseract.tesseract_cmd=TESSERACT_PATH
 sct=mss.mss()
 if MONITOR_NUMBER>=len(sct.monitors):print("Monitor does not exist. Available:",len(sct.monitors)-1);return
 monitor=sct.monitors[MONITOR_NUMBER]; print("Using monitor:",monitor)
 ot=threading.Thread(target=ocr_worker,daemon=True);dt=threading.Thread(target=buttplug_thread_worker,daemon=True);ot.start();dt.start()
 heartbeat_active=False;heartbeat_visible=False;heartbeat_ready=True;heartbeat_pulses=0;last_hb=0.0;hb_gone=0.0
 health_baseline=None;last_flash=0.0;flash_count=0
 current_action=None;candidate=None;confirm=0;missing=0;last_scan=-1;started=0.0;ui_lost=0
 detected_text="";detected_score=0.0;ocr_preview=None;fps=0.0;frames=0;fps_timer=time.time()
 try:
  while True:
   now=time.time(); hf=get_region_image(sct,monitor,regions["heartbeat"]); health=get_region_image(sct,monitor,regions["health"]); af=get_region_image(sct,monitor,regions["action_bar"])
   with ocr_lock:latest_action_frame=af.copy()
   hb,nred,_=detect_heartbeat(hf)
   if hb:
    last_hb=now
    if not heartbeat_visible:
     heartbeat_visible=True
     if heartbeat_ready:heartbeat_pulses+=1;heartbeat_ready=False;print(">>> HEARTBEAT PULSE",heartbeat_pulses,"| red:",nred)
    if not heartbeat_active:heartbeat_active=True;print(">>> HEARTBEAT STARTED");send_device_event("HEARTBEAT_START")
   else:
    if heartbeat_visible:heartbeat_visible=False;hb_gone=now
    if not heartbeat_ready and hb_gone and now-hb_gone>=HEARTBEAT_RESET_TIME:heartbeat_ready=True
   if heartbeat_active and now-last_hb>HEARTBEAT_TIMEOUT:heartbeat_active=False;print("<<< HEARTBEAT STOPPED");send_device_event("HEARTBEAT_END")
   red,_=detect_health_red(health)
   if health_baseline is None:health_baseline=float(red)
   change=red-health_baseline;flash=red>=HEALTH_FLASH_ABSOLUTE_THRESHOLD and change>=HEALTH_FLASH_INCREASE_THRESHOLD
   if flash and now-last_flash>=HEALTH_FLASH_COOLDOWN:
    flash_count+=1;last_flash=now;print(">>> HEALTH RED FLASH DETECTED | current:",red,"baseline:",round(health_baseline,1),"increase:",round(change,1));send_device_event("INJURY")
   if not flash:health_baseline=(1-HEALTH_BASELINE_ALPHA)*health_baseline+HEALTH_BASELINE_ALPHA*red
   with ocr_lock:
    scan=ocr_result["scan_id"];detected_action=ocr_result["action"];detected_text=ocr_result["text"];detected_score=ocr_result["score"]
    if ocr_result["preview"] is not None:ocr_preview=ocr_result["preview"].copy()
   if scan!=last_scan:
    last_scan=scan
    if detected_action is not None:
     missing=0
     if detected_action==candidate:confirm+=1
     else:candidate=detected_action;confirm=1
     if confirm>=ACTION_CONFIRMATIONS and current_action!=candidate:
      if current_action is not None:send_device_event("ACTION_END",current_action)
      current_action=candidate;started=now;ui_lost=0;print(">>> ACTION STARTED:",current_action,"| OCR:",detected_text);send_device_event("ACTION_START",current_action)
    else:
     candidate=None;confirm=0;missing+=1
     if missing>=ACTION_LOST_CONFIRMATIONS:
      if current_action is not None:
       old=current_action;current_action=None;print("<<< ACTION ENDED:",old,"(OCR disappeared)");send_device_event("ACTION_END",old)
      missing=0;ui_lost=0
   ui_present,ui_score,_=detect_action_ui(af)
   if current_action is not None and now-started>=ACTION_UI_GRACE_TIME:
    ui_lost=0 if ui_present else ui_lost+1
    if ui_lost>=ACTION_UI_LOST_FRAMES:
     old=current_action;current_action=None;candidate=None;confirm=missing=ui_lost=0;print("<<< ACTION ENDED:",old,"(UI disappeared)");send_device_event("ACTION_END",old)
   frames+=1
   if now-fps_timer>=1:fps=frames/(now-fps_timer);frames=0;fps_timer=now
   with device_status_lock:status=device_status.copy()
   display=np.zeros((850,1150,3),dtype=np.uint8);display[0:390,0:500]=cv2.resize(hf,(500,390));display[0:180,520:860]=cv2.resize(af,(340,180));display[570:780,10:260]=cv2.resize(health,(250,210))
   def txt(s,x,y,size=.55):cv2.putText(display,s,(x,y),cv2.FONT_HERSHEY_SIMPLEX,size,(255,255,255),2)
   txt("HEARTBEAT: "+("ACTIVE" if heartbeat_active else "INACTIVE"),10,425,.75);txt(f"Heartbeat red pixels: {nred}",10,460);txt(f"Heartbeat pulses: {heartbeat_pulses}",10,495)
   txt("ACTION: "+(current_action or "NONE"),520,220,.75);txt("OCR: "+detected_text[:30],520,255,.5);txt(f"Match: {detected_score:.2f}",520,285,.5);txt(f"Action UI: {ui_present} ({ui_score:.3f})",520,315,.5)
   if ocr_preview is not None and ocr_preview.size:
    p=ocr_preview if len(ocr_preview.shape)==3 else cv2.cvtColor(ocr_preview,cv2.COLOR_GRAY2BGR);display[395:575,520:1020]=cv2.resize(p,(500,180))
   txt("SURVIVOR HUD / INJURY FLASH",10,545);txt(f"Current red: {red}",280,600);txt(f"Baseline red: {health_baseline:.1f}",280,635);txt(f"Red increase: {change:.1f}",280,670);txt(f"Injury flashes: {flash_count}",280,705)
   txt("INTIFACE: "+("CONNECTED" if status["connected"] else "DISCONNECTED"),520,615,.65);txt(f"Devices: {status['device_count']}",520,650);txt(f"Output: {status['output_strength']*100:.0f}%",520,685);txt("Heartbeat buzz: "+("ON" if status["heartbeat_active"] else "OFF"),520,720,.5);txt("Last event: "+status["last_event"][:35],520,750,.5);txt(f"FPS: {fps:.1f}",950,30)
   cv2.imshow(WINDOW_NAME,display)
   if cv2.waitKey(1)&0xFF==ord('q'):break
 finally:
  with ocr_lock:ocr_result["running"]=False
  send_device_event("SHUTDOWN");ot.join(timeout=1);dt.join(timeout=3);cv2.destroyAllWindows();print("Detector stopped.")

if __name__=="__main__":main()
