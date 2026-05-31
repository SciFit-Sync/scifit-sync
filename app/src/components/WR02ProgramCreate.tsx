import {
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  Modal,
  Animated,
  ScrollView,
} from "react-native";
import { useState, useRef, useEffect } from "react";
import { colors } from "../assets/colors/colors";
import { Octicons } from "@expo/vector-icons";

interface Routine {
  id: string;
  name: string;
  gym: string;
  date: string;
}

interface ProgramCreateProps {
  routines: Routine[];
  onConfirm: (data: {
    program_name: string;
    selected_routine_ids: string[];
  }) => void;
  onClose: () => void;
}

export default function ProgramCreate({
  routines,
  onConfirm,
  onClose,
}: ProgramCreateProps) {
  const [program_name, set_program_name] = useState("");
  const [selected_ids, set_selected_ids] = useState<string[]>([]);

  const slide_anim = useRef(new Animated.Value(600)).current;

  useEffect(() => {
    Animated.timing(slide_anim, {
      toValue: 0,
      duration: 300,
      useNativeDriver: true,
    }).start();
  }, []);

  const handle_close = () => {
    Animated.timing(slide_anim, {
      toValue: 600,
      duration: 300,
      useNativeDriver: true,
    }).start(() => onClose());
  };

  const toggle_routine = (id: string) => {
    set_selected_ids((prev) =>
      prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id],
    );
  };

  const handle_confirm = () => {
    onConfirm({
      program_name,
      selected_routine_ids: selected_ids,
    });
  };

  return (
    <Modal
      transparent
      animationType="fade"
      visible
      onRequestClose={handle_close}
    >
      <View style={styles.overlay}>
        {/* 딤 배경 */}
        <TouchableOpacity
          style={styles.dim}
          activeOpacity={1}
          onPress={handle_close}
        />

        {/* 바텀시트 */}
        <Animated.View
          style={[styles.sheet, { transform: [{ translateY: slide_anim }] }]}
        >
          {/* 헤더 */}
          <View style={styles.sheet_header}>
            <View style={styles.placeholder} />
            <Text style={styles.sheet_title}>프로그램 생성</Text>
            <TouchableOpacity
              style={styles.close_button}
              onPress={handle_close}
            >
              <Octicons name="x" size={24} color={colors.primary} />
            </TouchableOpacity>
          </View>

          <ScrollView showsVerticalScrollIndicator={false} nestedScrollEnabled>
            {/* 프로그램명 입력 */}
            <View style={styles.field}>
              <Text style={styles.label}>프로그램 명</Text>
              <TextInput
                style={styles.input}
                placeholder="프로그램 명 입력"
                placeholderTextColor={colors.border}
                value={program_name}
                onChangeText={set_program_name}
              />
            </View>

            {/* 루틴 선택 */}
            <View style={[styles.field, { marginTop: 16 }]}>
              <Text style={styles.label}>루틴 선택</Text>
              <View style={styles.routine_list}>
                {routines.map((routine) => {
                  const is_selected = selected_ids.includes(routine.id);
                  return (
                    <TouchableOpacity
                      key={routine.id}
                      style={[
                        styles.routine_item,
                        is_selected && styles.routine_item_active,
                      ]}
                      onPress={() => toggle_routine(routine.id)}
                      activeOpacity={0.8}
                    >
                      <View style={styles.routine_info}>
                        <Text
                          style={[
                            styles.routine_name,
                            is_selected && styles.routine_name_active,
                          ]}
                        >
                          {routine.name}
                        </Text>
                        <Text style={styles.routine_sub}>{routine.gym}</Text>
                        <Text style={styles.routine_sub}>{routine.date}</Text>
                      </View>
                      {is_selected && (
                        <Octicons
                          name="check"
                          size={20}
                          color={colors.primary}
                        />
                      )}
                    </TouchableOpacity>
                  );
                })}
              </View>
            </View>
          </ScrollView>

          {/* 확인 버튼 */}
          <TouchableOpacity
            style={[
              styles.confirm_button,
              (!program_name || selected_ids.length === 0) &&
                styles.confirm_button_disabled,
            ]}
            onPress={handle_confirm}
            disabled={!program_name || selected_ids.length === 0}
            activeOpacity={0.8}
          >
            <Text style={styles.confirm_button_text}>
              {selected_ids.length > 0
                ? `확인 (${selected_ids.length}개 선택)`
                : "확인"}
            </Text>
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
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    paddingHorizontal: 20,
    paddingBottom: 40,
    paddingTop: 20,
    maxHeight: "85%",
  },
  sheet_header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 32,
  },
  placeholder: {
    width: 24,
  },
  close_button: {
    width: 24,
    alignItems: "center",
  },
  sheet_title: {
    fontFamily: "semibold",
    fontSize: 18,
    color: colors.primary,
    textAlign: "center",
    flex: 1,
  },
  field: {
    gap: 8,
  },
  label: {
    fontFamily: "medium",
    fontSize: 16,
    color: colors.primary,
  },
  input: {
    fontFamily: "regular",
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 10,
    fontSize: 14,
    color: colors.primary,
  },
  routine_list: {
    gap: 16,
    paddingBottom: 16,
  },
  routine_item: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    paddingHorizontal: 20,
    paddingVertical: 14,
    height: 90,
  },
  routine_item_active: {
    borderColor: colors.primary,
    backgroundColor: colors.select,
  },
  routine_info: {
    gap: 4,
  },
  routine_name: {
    fontFamily: "medium",
    fontSize: 16,
    color: colors.primary,
  },
  routine_name_active: {
    color: colors.primary,
  },
  routine_sub: {
    fontFamily: "regular",
    fontSize: 12,
    color: colors.bluegray,
  },
  confirm_button: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 16,
  },
  confirm_button_disabled: {
    opacity: 0.5,
  },
  confirm_button_text: {
    fontFamily: "medium",
    fontSize: 16,
    color: colors.white,
  },
});
