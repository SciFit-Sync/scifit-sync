import {
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
  Modal,
  Animated,
} from "react-native";
import { Picker } from "@react-native-picker/picker";
import { useState, useRef, useEffect } from "react";
import { colors } from "../assets/colors/colors";
import { Octicons } from "@expo/vector-icons";

interface TimerPickerBottomSheetProps {
  initial_seconds: number;
  onConfirm: (seconds: number) => void;
  onClose: () => void;
}

export default function TimerPickerBottomSheet({
  initial_seconds,
  onConfirm,
  onClose,
}: TimerPickerBottomSheetProps) {
  const [selected_minutes, set_selected_minutes] = useState(
    Math.floor(initial_seconds / 60),
  );
  const [selected_seconds, set_selected_seconds] = useState(
    initial_seconds % 60,
  );

  const slide_anim = useRef(new Animated.Value(500)).current;

  useEffect(() => {
    Animated.timing(slide_anim, {
      toValue: 0,
      duration: 300,
      useNativeDriver: true,
    }).start();
  }, []);

  const handle_confirm = () => {
    const total = selected_minutes * 60 + selected_seconds;
    onConfirm(total < 10 ? 10 : total); // 최소 10초
  };

  const minutes = Array.from({ length: 10 }, (_, i) => i); // 0~9분
  const seconds_list = Array.from({ length: 60 }, (_, i) => i); // 0~59초

  return (
    <Modal transparent animationType="fade" visible onRequestClose={onClose}>
      <View style={styles.overlay}>
        <TouchableOpacity
          style={styles.dim}
          activeOpacity={1}
          onPress={onClose}
        />
        <Animated.View
          style={[styles.sheet, { transform: [{ translateY: slide_anim }] }]}
        >
          <View style={styles.sheet_header}>
            <View style={styles.placeholder} />
            <Text style={styles.sheet_title}>휴식 시간 설정</Text>
            <TouchableOpacity style={styles.close_button} onPress={onClose}>
              <Octicons name="x" size={32} color={colors.primary} />
            </TouchableOpacity>
          </View>

          <View style={styles.picker_container}>
            <Picker
              style={styles.picker}
              selectedValue={selected_minutes}
              onValueChange={(v) => set_selected_minutes(Number(v))}
              itemStyle={styles.picker_item}
            >
              {minutes.map((m) => (
                <Picker.Item
                  key={m}
                  label={`${m}분`}
                  value={m}
                  color={selected_minutes === m ? colors.primary : colors.button}
                />
              ))}
            </Picker>

            <Picker
              style={styles.picker}
              selectedValue={selected_seconds}
              onValueChange={(v) => set_selected_seconds(Number(v))}
              itemStyle={styles.picker_item}
            >
              {seconds_list.map((s) => (
                <Picker.Item
                  key={s}
                  label={`${s}초`}
                  value={s}
                  color={selected_seconds === s ? colors.primary : colors.button}
                />
              ))}
            </Picker>
          </View>

          <TouchableOpacity
            style={styles.confirm_button}
            onPress={handle_confirm}
            activeOpacity={0.8}
          >
            <Text style={styles.confirm_button_text}>확인</Text>
          </TouchableOpacity>
        </Animated.View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    justifyContent: "flex-end",
    backgroundColor: "rgba(0,0,0,0.2)",
  },
  dim: { flex: 1 },
  sheet: {
    backgroundColor: colors.white,
    borderTopLeftRadius: 30,
    borderTopRightRadius: 30,
    paddingHorizontal: 20,
    paddingBottom: 40,
    paddingTop: 20,
    height: 380,
  },
  sheet_header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 8,
  },
  placeholder: { width: 32 },
  close_button: { width: 32, alignItems: "center" },
  sheet_title: {
    fontFamily: "semibold",
    fontSize: 18,
    color: colors.primary,
    textAlign: "center",
    flex: 1,
  },
  picker_container: {
    flexDirection: "row",
    flex: 1,
  },
  picker: { flex: 1 },
  picker_item: {
    fontFamily: "regular",
    fontSize: 16,
    color: colors.primary,
  },
  confirm_button: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
    marginTop: 8,
  },
  confirm_button_text: {
    fontFamily: "medium",
    fontSize: 16,
    color: colors.white,
  },
});
