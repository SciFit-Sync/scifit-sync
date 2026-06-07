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

const MIN_SECONDS = 10;

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

  const total = selected_minutes * 60 + selected_seconds;
  const is_valid = total >= MIN_SECONDS;

  const handle_confirm = () => {
    if (!is_valid) return;
    onConfirm(total);
  };

  const minutes = Array.from({ length: 10 }, (_, i) => i);
  const seconds_list = Array.from({ length: 60 }, (_, i) => i);

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
          <View style={styles.sheetHeader}>
            <View style={styles.placeholder} />
            <Text style={styles.sheetTitle}>휴식 시간 설정</Text>
            <TouchableOpacity style={styles.closeButton} onPress={onClose}>
              <Octicons name="x" size={32} color={colors.primary} />
            </TouchableOpacity>
          </View>

          <View style={styles.pickerContainer}>
            <Picker
              style={styles.picker}
              selectedValue={selected_minutes}
              onValueChange={(v) => set_selected_minutes(Number(v))}
              itemStyle={styles.pickerItem}
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
              itemStyle={styles.pickerItem}
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

          {!is_valid && (
            <Text style={styles.hint}>최소 {MIN_SECONDS}초 이상 설정해주세요</Text>
          )}

          <TouchableOpacity
            style={[styles.confirmButton, !is_valid && styles.confirmButtonDisabled]}
            onPress={handle_confirm}
            disabled={!is_valid}
            activeOpacity={0.8}
          >
            <Text style={styles.confirmButtonText}>확인</Text>
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
  dim: {
    flex: 1,
  },
  sheet: {
    backgroundColor: colors.white,
    borderTopLeftRadius: 30,
    borderTopRightRadius: 30,
    paddingHorizontal: 20,
    paddingBottom: 40,
    paddingTop: 20,
    height: 410,
  },
  sheetHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 8,
  },
  placeholder: {
    width: 32,
  },
  closeButton: {
    width: 32,
    alignItems: "center",
  },
  sheetTitle: {
    fontFamily: "semibold",
    fontSize: 18,
    color: colors.primary,
    textAlign: "center",
    flex: 1,
  },
  pickerContainer: {
    flexDirection: "row",
    flex: 1,
  },
  picker: {
    flex: 1,
  },
  pickerItem: {
    fontFamily: "regular",
    fontSize: 16,
    color: colors.primary,
  },
  hint: {
    fontFamily: "regular",
    fontSize: 12,
    color: "#FF3B30",
    textAlign: "center",
    marginBottom: 4,
  },
  confirmButton: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
    marginTop: 8,
  },
  confirmButtonDisabled: {
    opacity: 0.4,
  },
  confirmButtonText: {
    fontFamily: "medium",
    fontSize: 16,
    color: colors.white,
  },
});
